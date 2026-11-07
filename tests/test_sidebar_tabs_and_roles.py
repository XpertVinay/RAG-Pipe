"""Unit and integration tests for sidebar tabs and super-admin role enforcement."""

import pytest
from fastapi import HTTPException

from app.core.auth import is_super_admin, require_super_admin, is_admin, is_admin_or_staff
from app.models.user import User


def test_is_super_admin_role_checks():
    """Verify is_super_admin strictly validates super-admin privileges."""
    assert is_super_admin(User(id="1", username="root", email="root@test.com", role="super_admin")) is True
    assert is_super_admin(User(id="2", username="sa", email="sa@test.com", role="superadmin")) is True
    assert is_super_admin(User(id="3", username="sa2", email="sa2@test.com", role="super-admin")) is True

    # Other roles must be False
    assert is_super_admin(User(id="4", username="adm", email="adm@test.com", role="admin")) is False
    assert is_super_admin(User(id="5", username="stf", email="stf@test.com", role="staff")) is False
    assert is_super_admin(User(id="6", username="usr", email="usr@test.com", role="user")) is False
    assert is_super_admin(None) is False


@pytest.mark.asyncio
async def test_require_super_admin_dependency():
    """Verify require_super_admin allows super_admin and blocks all other roles with 403."""
    super_admin_user = User(id="1", username="root", email="root@test.com", role="super_admin")
    result = await require_super_admin(super_admin_user)
    assert result == super_admin_user

    admin_user = User(id="2", username="adm", email="adm@test.com", role="admin")
    with pytest.raises(HTTPException) as exc_info:
        await require_super_admin(admin_user)
    assert exc_info.value.status_code == 403

    normal_user = User(id="3", username="usr", email="usr@test.com", role="user")
    with pytest.raises(HTTPException) as exc_info:
        await require_super_admin(normal_user)
    assert exc_info.value.status_code == 403


def test_sidebar_html_tab_defaults():
    """Verify that sidebar template sets Agents tab to display: none by default."""
    with open("app/templates/components/sidebar.html", "r", encoding="utf-8") as f:
        content = f.read()

    # Agents tab must be hidden by default
    assert 'id="tab-btn-agents"' in content
    assert 'id="tab-btn-agents" data-tab="agents"' in content
    assert 'style="display: none;"' in content


def test_sidebar_css_no_truncation():
    """Verify that sidebar.css prevents label truncation on tabs."""
    with open("app/static/css/sidebar.css", "r", encoding="utf-8") as f:
        css = f.read()

    # .sidebar-tab should have min-width: max-content
    assert "min-width: max-content;" in css
    # .sidebar-tab .tab-label should have overflow: visible and text-overflow: clip
    assert "overflow: visible;" in css
    assert "text-overflow: clip;" in css
