"""Thin Flask routes for the protected administration dashboard."""

from __future__ import annotations

import uuid

from flask import abort, current_app, flash, redirect, render_template, request, url_for

from app.blueprints.admin import bp
from app.extensions import db
from app.rag.embeddings import EmbeddingError, build_embedding_provider
from app.services.admin_dashboard_service import AdminDashboardService
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


def _page_arg() -> int:
    try:
        return max(1, int(request.args.get("page", 1)))
    except (TypeError, ValueError):
        return 1


@bp.get("/")
def dashboard():
    return render_template("admin/dashboard.html", overview=_dashboard().overview())


@bp.get("/cars")
def cars():
    page = _dashboard().cars(page=_page_arg())
    return render_template("admin/cars.html", page=page)


@bp.get("/test-drives")
def test_drives():
    page = _dashboard().test_drives(page=_page_arg())
    return render_template("admin/test_drives.html", page=page)


@bp.get("/leads")
def leads():
    page = _dashboard().sales_leads(page=_page_arg())
    return render_template("admin/leads.html", page=page)


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
    except (EmbeddingError, KnowledgeIndexingError, KnowledgePersistenceError, KnowledgeNotFoundError) as exc:
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
