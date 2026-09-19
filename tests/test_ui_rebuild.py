"""Customer UI v2 regression contracts."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_base_uses_one_customer_design_system() -> None:
    source = _source("app/templates/base.html")

    assert "css/ui-v2.css" in source
    assert "css/site.css" not in source
    assert "css/customer-ui.css" not in source
    assert 'id="nav-toggle"' in source
    assert 'id="primary-nav"' in source
    assert "static_asset('css/ui-v2.css')" in source


def test_chat_template_has_no_uncompiled_tailwind_utility_markup() -> None:
    source = _source("app/templates/chat/index.html")

    assert 'class="chat-app"' in source
    assert "chat-layout" in source
    assert 'id="recommendation-grid"' in source
    assert "bg-[#" not in source
    assert "text-[#" not in source
    assert "lg:" not in source
    assert "grid-cols-" not in source
    assert 'id="sidebar-backdrop"' in source
    assert 'aria-controls="chat-sidebar"' in source
    assert 'for="chat-input"' in source


def test_chat_dynamic_renderer_uses_semantic_classes_and_text_content() -> None:
    source = _source("app/static/js/chat.js")

    assert 'card.className = "rec-card"' in source
    assert 'wrapper.className = "selected-car-summary"' in source
    assert "bg-[#" not in source
    assert "text-[#" not in source
    assert ".innerHTML" not in source
    assert ".textContent" in source
    assert 'historyList.addEventListener("click"' in source
    assert 'recommendationSection.addEventListener("click"' in source


def test_chat_v2_styles_cover_desktop_and_mobile_shell() -> None:
    source = _source("app/static/css/chat-v2.css")

    assert ".chat-layout" in source
    assert ".chat-panel" in source
    assert ".recommendation-grid" in source
    assert ".chat-sidebar.open" in source
    assert "@media(max-width:650px)" in source


def test_admin_v2_styles_cover_real_filter_and_form_controls() -> None:
    source = _source("app/static/css/admin.css")

    assert ".admin-filter-form" in source
    assert ".admin-form-grid" in source
    assert ".admin-form select" in source
    assert ".admin-filter-form input" in source
    assert ".table-wrap" in source
    assert "@media(max-width:760px)" in source


def test_customer_pages_render_v2_assets(app, client) -> None:
    home = client.get("/")
    home_body = home.get_data(as_text=True)
    assert home.status_code == 200
    assert "css/ui-v2.css" in home_body
    assert "css/site.css" not in home_body

    chat = client.get("/chat")
    chat_body = chat.get_data(as_text=True)
    assert chat.status_code == 200
    assert "css/ui-v2.css" in chat_body
    assert "css/chat-v2.css" in chat_body
    assert "bg-[#" not in chat_body
    assert re.search(r"css/ui-v2\.css\?v=[a-f0-9]{12}", home_body)
    assert re.search(r"css/chat-v2\.css\?v=[a-f0-9]{12}", chat_body)


def test_legacy_customer_stylesheets_are_removed() -> None:
    assert not (ROOT / "app/static/css/site.css").exists()
    assert not (ROOT / "app/static/css/customer-ui.css").exists()


def test_auth_uses_hashed_asset_and_explains_account_sync(app, unauthed_client) -> None:
    response = unauthed_client.get("/auth/login")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert re.search(r"css/auth\.css\?v=[a-f0-9]{12}", body)
    assert "المتابعة باستخدام Google" in body
    assert "هيتجهز تلقائيًا" in body
