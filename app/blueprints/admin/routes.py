"""Thin Flask routes for the protected administration dashboard."""

from __future__ import annotations

import uuid

from flask import abort, current_app, flash, redirect, render_template, request, url_for

from app.blueprints.admin import bp
from app.extensions import db
from app.rag.embeddings import EmbeddingError, build_embedding_provider
from app.services.admin_dashboard_service import (
    AdminDashboardService,
    AdminNotFoundError,
    AdminPersistenceError,
    AdminValidationError,
)
from app.services.car_image_upload_service import (
    CarImageStorageError,
    CarImageValidationError,
    SupabaseCarImageStorage,
    ValidatedCarImage,
    validate_car_image,
)
from app.services.knowledge_service import (
    KnowledgeIndexingError,
    KnowledgeNotFoundError,
    KnowledgePersistenceError,
    KnowledgeService,
)


def _dashboard() -> AdminDashboardService:
    return AdminDashboardService(db.session)


def _knowledge() -> KnowledgeService:
    return KnowledgeService(db.session, build_embedding_provider(current_app.config))


def _image_storage() -> SupabaseCarImageStorage:
    return SupabaseCarImageStorage(
        supabase_url=current_app.config.get("SUPABASE_URL"),
        secret_key=current_app.config.get("SUPABASE_SECRET_KEY"),
        bucket=current_app.config.get("CAR_IMAGE_BUCKET", "car-images"),
    )


def _validated_image_upload() -> ValidatedCarImage | None:
    return validate_car_image(
        request.files.get("car_image"),
        max_bytes=int(current_app.config.get("MAX_CAR_IMAGE_BYTES", 5 * 1024 * 1024)),
    )


def _attach_uploaded_image(car_id: int, image: ValidatedCarImage) -> bool:
    """Upload and attach an image, cleaning up the new object if DB persistence fails."""

    storage = _image_storage()
    storage_path = storage.upload(car_id, image)
    try:
        _dashboard().set_car_image_path(car_id, storage_path)
    except (AdminNotFoundError, AdminPersistenceError):
        try:
            storage.delete(storage_path)
        except CarImageStorageError:
            current_app.logger.exception("Failed to clean up unattached car image")
        raise
    return True


def _page_arg() -> int:
    try:
        return max(1, int(request.args.get("page", 1)))
    except (TypeError, ValueError):
        return 1


def _car_filters() -> tuple[str, str | None, bool | None, str]:
    query = request.args.get("q", "").strip()
    condition_raw = request.args.get("condition", "").strip().lower()
    condition = condition_raw if condition_raw in {"new", "used"} else None
    active_raw = request.args.get("active", "all").strip().lower()
    if active_raw == "active":
        active = True
    elif active_raw == "inactive":
        active = False
    else:
        active = None
        active_raw = "all"
    return query, condition, active, active_raw


@bp.get("/")
def dashboard():
    return render_template("admin/dashboard.html", overview=_dashboard().overview())


@bp.get("/cars")
def cars():
    query, condition, active, active_label = _car_filters()
    page = _dashboard().cars(
        page=_page_arg(),
        query=query,
        condition=condition,
        active=active,
    )
    return render_template(
        "admin/cars.html",
        page=page,
        filters={
            "q": query,
            "condition": condition or "",
            "active": active_label,
        },
    )


@bp.route("/cars/new", methods=["GET", "POST"])
def car_new():
    if request.method == "GET":
        return render_template("admin/car_form.html", car=None)

    try:
        image = _validated_image_upload()
        car = _dashboard().create_car(
            request.form,
            active=request.form.get("active") == "on",
        )
    except (AdminValidationError, CarImageValidationError) as exc:
        current_app.logger.info("Admin car create validation failed: %s", exc)
        flash("راجع بيانات السيارة والصورة؛ المسموح JPG أو PNG أو WebP حتى 5MB.", "error")
        return render_template("admin/car_form.html", car=None), 400
    except AdminPersistenceError:
        current_app.logger.exception("Admin car create failed")
        flash("تعذر حفظ السيارة حاليًا.", "error")
        return redirect(url_for("site.admin.cars"))

    if image is not None:
        try:
            _attach_uploaded_image(car.id, image)
        except (CarImageStorageError, AdminNotFoundError, AdminPersistenceError):
            current_app.logger.exception("Admin car image upload failed")
            flash(
                f"تمت إضافة السيارة #{car.id} لكن رفع الصورة فشل؛ يمكنك إعادة المحاولة من التعديل.",
                "error",
            )
            return redirect(url_for("site.admin.car_edit", car_id=car.id))

    flash(f"تمت إضافة السيارة #{car.id}: {car.brand} {car.model}", "success")
    return redirect(url_for("site.admin.cars"))


@bp.route("/cars/<int:car_id>/edit", methods=["GET", "POST"])
def car_edit(car_id: int):
    car = _dashboard().car(car_id)
    if car is None:
        abort(404)
    if request.method == "GET":
        return render_template("admin/car_form.html", car=car)

    try:
        image = _validated_image_upload()
        car = _dashboard().update_car(
            car_id,
            request.form,
            active=request.form.get("active") == "on",
        )
    except (AdminValidationError, CarImageValidationError) as exc:
        current_app.logger.info("Admin car update validation failed: %s", exc)
        flash("راجع بيانات السيارة والصورة؛ المسموح JPG أو PNG أو WebP حتى 5MB.", "error")
        return render_template("admin/car_form.html", car=car), 400
    except AdminNotFoundError:
        abort(404)
    except AdminPersistenceError:
        current_app.logger.exception("Admin car update failed")
        flash("تعذر تحديث السيارة حاليًا.", "error")
        return redirect(url_for("site.admin.cars"))

    if image is not None:
        previous_path = car.image_storage_path
        try:
            _attach_uploaded_image(car.id, image)
            db.session.refresh(car)
            if previous_path and previous_path != car.image_storage_path:
                try:
                    _image_storage().delete(previous_path)
                except CarImageStorageError:
                    current_app.logger.warning(
                        "Old car image cleanup failed for car %s", car.id, exc_info=True
                    )
        except (CarImageStorageError, AdminNotFoundError, AdminPersistenceError):
            current_app.logger.exception("Admin car image replacement failed")
            flash(
                "تم تحديث بيانات السيارة لكن تعذر تحديث الصورة؛ الصورة السابقة ما زالت موجودة.",
                "error",
            )
            return redirect(url_for("site.admin.car_edit", car_id=car.id))

    flash(f"تم تحديث السيارة #{car.id}.", "success")
    return redirect(url_for("site.admin.cars"))


@bp.post("/cars/<int:car_id>/deactivate")
def car_deactivate(car_id: int):
    try:
        car = _dashboard().deactivate_car(car_id)
    except AdminNotFoundError:
        abort(404)
    except AdminPersistenceError:
        current_app.logger.exception("Admin car deactivation failed")
        flash("تعذر تعطيل السيارة حاليًا.", "error")
        return redirect(url_for("site.admin.cars"))

    flash(f"تم تعطيل السيارة #{car.id} من نتائج الكتالوج النشطة.", "success")
    return redirect(url_for("site.admin.cars"))


@bp.get("/test-drives")
def test_drives():
    page = _dashboard().test_drives(page=_page_arg())
    return render_template("admin/test_drives.html", page=page)


@bp.post("/test-drives/<int:request_id>/status")
def test_drive_status(request_id: int):
    try:
        item = _dashboard().update_test_drive_status(
            request_id,
            request.form.get("status", ""),
        )
    except AdminNotFoundError:
        abort(404)
    except AdminValidationError:
        flash("انتقال حالة Test Drive غير مسموح من الحالة الحالية.", "error")
        return redirect(url_for("site.admin.test_drives"))
    except AdminPersistenceError:
        current_app.logger.exception("Admin test drive status update failed")
        flash("تعذر تحديث حالة Test Drive حاليًا.", "error")
        return redirect(url_for("site.admin.test_drives"))

    flash(f"تم تحديث Test Drive #{item.id} إلى {item.status}.", "success")
    return redirect(url_for("site.admin.test_drives"))


@bp.get("/leads")
def leads():
    page = _dashboard().sales_leads(page=_page_arg())
    return render_template("admin/leads.html", page=page)


@bp.post("/leads/<int:lead_id>/status")
def lead_status(lead_id: int):
    try:
        item = _dashboard().update_sales_lead_status(
            lead_id,
            request.form.get("status", ""),
        )
    except AdminNotFoundError:
        abort(404)
    except AdminValidationError:
        flash("انتقال حالة Sales Lead غير مسموح من الحالة الحالية.", "error")
        return redirect(url_for("site.admin.leads"))
    except AdminPersistenceError:
        current_app.logger.exception("Admin sales lead status update failed")
        flash("تعذر تحديث حالة Sales Lead حاليًا.", "error")
        return redirect(url_for("site.admin.leads"))

    flash(f"تم تحديث Sales Lead #{item.id} إلى {item.status}.", "success")
    return redirect(url_for("site.admin.leads"))


@bp.get("/knowledge")
def knowledge_list():
    documents = _dashboard().knowledge_documents()
    return render_template("admin/knowledge/list.html", documents=documents)


@bp.route("/knowledge/new", methods=["GET", "POST"])
def knowledge_new():
    if request.method == "GET":
        return render_template("admin/knowledge/form.html", document=None)

    try:
        document = _knowledge().create_document(
            title=request.form.get("title", ""),
            category=request.form.get("category", ""),
            content=request.form.get("content", ""),
            active=request.form.get("active") == "on",
        )
    except ValueError:
        flash("راجع العنوان والـcategory والمحتوى؛ الحقول المطلوبة لا تقبل قيمًا فارغة.", "error")
        return redirect(url_for("site.admin.knowledge_new"))
    except KnowledgeIndexingError as exc:
        current_app.logger.warning("Admin knowledge create indexing failed: %s", type(exc).__name__)
        flash("تم حفظ المستند لكن الفهرسة فشلت. راجع حالته ثم استخدم Reindex.", "error")
        return redirect(url_for("site.admin.knowledge_list"))
    except (EmbeddingError, KnowledgePersistenceError) as exc:
        current_app.logger.warning("Admin knowledge create failed: %s", type(exc).__name__)
        flash("تعذر إضافة مستند المعرفة حاليًا.", "error")
        return redirect(url_for("site.admin.knowledge_list"))

    flash(f"تمت إضافة المعرفة: {document.title}", "success")
    return redirect(url_for("site.admin.knowledge_list"))


@bp.route("/knowledge/<uuid:document_id>/edit", methods=["GET", "POST"])
def knowledge_edit(document_id: uuid.UUID):
    document = _dashboard().knowledge_document(document_id)
    if document is None:
        abort(404)

    if request.method == "GET":
        return render_template("admin/knowledge/form.html", document=document)

    try:
        document = _knowledge().update_document(
            document_id,
            title=request.form.get("title", ""),
            category=request.form.get("category", ""),
            content=request.form.get("content", ""),
            active=request.form.get("active") == "on",
        )
    except ValueError:
        flash("راجع العنوان والـcategory والمحتوى؛ الحقول المطلوبة لا تقبل قيمًا فارغة.", "error")
        return redirect(url_for("site.admin.knowledge_edit", document_id=document_id))
    except KnowledgeIndexingError as exc:
        current_app.logger.warning("Admin knowledge update indexing failed: %s", type(exc).__name__)
        flash("تم حفظ التعديل لكن إعادة الفهرسة فشلت. راجع الحالة ثم استخدم Reindex.", "error")
        return redirect(url_for("site.admin.knowledge_list"))
    except (EmbeddingError, KnowledgePersistenceError, KnowledgeNotFoundError) as exc:
        current_app.logger.warning("Admin knowledge update failed: %s", type(exc).__name__)
        flash("تعذر تحديث مستند المعرفة حاليًا.", "error")
        return redirect(url_for("site.admin.knowledge_list"))

    flash(f"تم تحديث المعرفة: {document.title}", "success")
    return redirect(url_for("site.admin.knowledge_list"))


@bp.post("/knowledge/<uuid:document_id>/reindex")
def knowledge_reindex(document_id: uuid.UUID):
    try:
        document = _knowledge().reindex_document(document_id)
    except (
        EmbeddingError,
        KnowledgeIndexingError,
        KnowledgePersistenceError,
        KnowledgeNotFoundError,
    ) as exc:
        current_app.logger.warning("Admin knowledge reindex failed: %s", type(exc).__name__)
        flash("إعادة الفهرسة فشلت. راجع حالة المستند وإعدادات الـembedding provider.", "error")
        return redirect(url_for("site.admin.knowledge_list"))

    flash(f"تمت إعادة فهرسة: {document.title}", "success")
    return redirect(url_for("site.admin.knowledge_list"))


@bp.post("/knowledge/<uuid:document_id>/delete")
def knowledge_delete(document_id: uuid.UUID):
    try:
        _knowledge().delete_document(document_id)
    except (KnowledgeNotFoundError, KnowledgePersistenceError) as exc:
        current_app.logger.warning("Admin knowledge delete failed: %s", type(exc).__name__)
        flash("تعذر حذف مستند المعرفة.", "error")
        return redirect(url_for("site.admin.knowledge_list"))

    flash("تم حذف مستند المعرفة وفهرسته المرتبطة.", "success")
    return redirect(url_for("site.admin.knowledge_list"))
