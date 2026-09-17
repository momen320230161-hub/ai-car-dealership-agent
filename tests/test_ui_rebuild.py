"""Customer UI v2 regression contracts."""

from __future__ import annotations

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


def test_chat_template_has_no_uncompiled_tailwind_utility_markup() -> None:
    source = _source("app/templates/chat/index.html")

    assert 'class="chat-app"' in source
    assert 'class="chat-layout"' in source
    assert 'id="recommendation-grid"' in source
    assert "bg-[#" not in source
    assert "text-[#" not in source
    assert "lg:" not in source
    assert "grid-cols-" not in source


def test_chat_dynamic_renderer_uses_semantic_classes_and_text_content() -> None:
    source = _source("app/static/js/chat.js")

    assert 'card.className = "rec-card"' in source
    assert 'wrapper.className = "selected-car-summary"' in source
    assert "bg-[#" not in source
    assert "text-[#" not in source
    assert ".innerHTML" not in source
    assert ".textContent" in source


def test_chat_v2_styles_cover_desktop_and_mobile_shell() -> None:
    source = _source("app/static/css/chat-v2.css")

    assert ".chat-layout" in source
    assert ".chat-panel" in source
    assert ".recommendation-grid" in source
    assert ".chat-sidebar.open" in source
    assert "@media(max-width:650px)" in source


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
