"""Thin customer website routes for landing, catalog, and car details."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from flask import abort, current_app, render_template, request
from sqlalchemy.exc import SQLAlchemyError

from app.blueprints.site import bp
from app.domain.catalog_filters import CatalogFilters
from app.extensions import db
from app.services.car_image_service import image_url_for_car
from app.services.customer_web_service import CustomerWebService

_SORTS = {
    "year_desc": "الأحدث",
    "price_asc": "السعر: الأقل أولاً",
    "price_desc": "السعر: الأعلى أولاً",
    "mileage_asc": "الممشى: الأقل أولاً",
}


def _service() -> CustomerWebService:
    return CustomerWebService(
        db.session,
        recent_message_limit=current_app.config["AGENT_RECENT_MESSAGE_LIMIT"],
    )


def _page_number() -> int:
    try:
        return max(1, int(request.args.get("page", "1")))
    except (TypeError, ValueError):
        return 1


def _catalog_filters() -> tuple[CatalogFilters, dict[str, str], str | None]:
    values = {
        "condition": request.args.get("condition", "").strip(),
        "brand": request.args.get("brand", "").strip(),
        "body_type": request.args.get("body_type", "").strip(),
        "max_price": request.args.get("max_price", "").strip(),
    }
    payload = {key: value for key, value in values.items() if value}
    try:
        return CatalogFilters.from_mapping(payload), values, None
    except ValueError:
        return CatalogFilters(), values, "راجع قيم الفلاتر وحاول تاني."


@bp.app_template_filter("egp")
def format_egp(value) -> str:
    """Format a recorded EGP price without changing its value."""
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return "—"
    return f"{amount:,.0f} ج.م"


@bp.app_template_filter("condition_ar")
def condition_ar(value: str | None) -> str:
    return {"new": "جديدة", "used": "مستعملة"}.get(str(value or "").lower(), "—")

@bp.app_template_filter("car_image_url")
def car_image_url(car) -> str | None:
    """Resolve a catalog car to its public Supabase image URL."""
    return image_url_for_car(car, supabase_url=current_app.config.get("SUPABASE_URL"))


@bp.app_template_filter("compact_number")
def compact_number(value) -> str:
    """Render recorded decimals without meaningless trailing zeroes."""

    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return "—"
    return format(amount.normalize(), "f")


@bp.get("/")
def home():
    service = _service()
    try:
        featured_cars = service.featured_cars(limit=3)
        catalog_count = service.catalog_count()
        catalog_available = True
    except (SQLAlchemyError, ValueError):
        db.session.rollback()
        current_app.logger.exception("Customer landing catalog summary failed")
        featured_cars = []
        catalog_count = None
        catalog_available = False
    return render_template(
        "home.html",
        featured_cars=featured_cars,
        catalog_count=catalog_count,
        catalog_available=catalog_available,
    )


@bp.get("/cars")
def cars():
    service = _service()
    filters, filter_values, filter_error = _catalog_filters()
    requested_sort = request.args.get("sort", "year_desc")
    sort_by = requested_sort if requested_sort in _SORTS else "year_desc"
    try:
        page = service.catalog_page(filters, page=_page_number(), sort_by=sort_by)
        facets = service.catalog_facets()
    except (SQLAlchemyError, ValueError):
        db.session.rollback()
        current_app.logger.exception("Customer catalog page failed")
        return render_template("errors/500.html"), 503

    return render_template(
        "catalog/index.html",
        catalog_page=page,
        facets=facets,
        filter_values=filter_values,
        filter_error=filter_error,
        sort_by=sort_by,
        sort_options=_SORTS,
    )


@bp.get("/cars/<int:car_id>")
def car_detail(car_id: int):
    try:
        car = _service().car_details(car_id)
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Customer car details query failed")
        return render_template("errors/500.html"), 503
    if car is None:
        abort(404)
    return render_template("catalog/detail.html", car=car)


@bp.app_errorhandler(404)
def not_found(error):
    del error
    return render_template("errors/404.html"), 404


@bp.app_errorhandler(403)
def forbidden(error):
    del error
    return render_template("errors/403.html"), 403


@bp.app_errorhandler(500)
def internal_error(error):
    current_app.logger.error("Unhandled customer web error: %s", error)
    db.session.rollback()
    return render_template("errors/500.html"), 500
