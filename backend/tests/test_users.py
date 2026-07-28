from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from app.api.deps import get_current_admin, get_current_user, get_db
from app.main import app
from fastapi import HTTPException
from fastapi.testclient import TestClient

client = TestClient(app)
mock_db = MagicMock()
mock_db.execute = AsyncMock()


@pytest.fixture(autouse=True)
def setup_db():
    async def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    yield
    if get_db in app.dependency_overrides:
        del app.dependency_overrides[get_db]


# Mock user fixtures
admin_user = MagicMock()
admin_user.id = uuid4()
admin_user.email = "admin@example.com"
admin_user.profile = MagicMock()
admin_user.profile.role = "admin"
admin_user.profile.username = "admin_user"

regular_user = MagicMock()
regular_user.id = uuid4()
regular_user.email = "user@example.com"
regular_user.profile = MagicMock()
regular_user.profile.role = "user"
regular_user.profile.username = "regular_user"


# Helper to override authorization dependencies for testing specific roles
def set_auth_overrides(current_user):
    app.dependency_overrides[get_current_user] = lambda: current_user
    if current_user and current_user.profile.role == "admin":
        app.dependency_overrides[get_current_admin] = lambda: current_user
    else:

        def raise_forbidden():
            raise HTTPException(status_code=403, detail="Not enough privileges")

        app.dependency_overrides[get_current_admin] = raise_forbidden


def clear_auth_overrides():
    if get_current_user in app.dependency_overrides:
        del app.dependency_overrides[get_current_user]
    if get_current_admin in app.dependency_overrides:
        del app.dependency_overrides[get_current_admin]


# --------------------------------------------------------------------------------
def test_list_users_as_admin_success():
    set_auth_overrides(admin_user)
    mock_db.reset_mock()

    mock_user = MagicMock()
    mock_user.id = uuid4()
    mock_user.email = "listed@example.com"
    mock_user.created_at = "2026-07-27T00:00:00Z"

    mock_profile = MagicMock()
    mock_profile.username = "listed_user"
    mock_profile.role = "user"
    mock_profile.display_name = "Listed User"
    mock_profile.avatar_key = None
    mock_profile.theme_preference = "default"
    mock_profile.id = mock_user.id
    mock_profile.created_at = "2026-07-27T00:00:00Z"

    mock_user.profile = mock_profile

    mock_result_users = MagicMock()
    mock_result_users.scalars().unique.return_value.all.return_value = [mock_user]

    mock_db.execute.side_effect = [mock_result_users]

    response = client.get("/admin/users?role=user&search=listed")
    assert response.status_code == 200
    users = response.json()
    assert len(users) == 1
    assert users[0]["email"] == "listed@example.com"
    assert users[0]["profile"]["username"] == "listed_user"

    clear_auth_overrides()


def test_list_users_as_regular_user_forbidden():
    set_auth_overrides(regular_user)
    response = client.get("/admin/users")
    assert response.status_code == 403
    assert response.json()["detail"] == "Not enough privileges"
    clear_auth_overrides()


def test_get_user_detail_as_admin_success():
    set_auth_overrides(admin_user)
    mock_db.reset_mock()

    target_id = uuid4()
    mock_user = MagicMock()
    mock_user.id = target_id
    mock_user.email = "detail@example.com"
    mock_user.created_at = "2026-07-27T00:00:00Z"

    mock_profile = MagicMock()
    mock_profile.username = "detail_user"
    mock_profile.role = "user"
    mock_profile.display_name = "Detail User"
    mock_profile.avatar_key = "avatar.png"
    mock_profile.theme_preference = "luxury"
    mock_profile.id = target_id
    mock_profile.created_at = "2026-07-27T00:00:00Z"

    mock_user.profile = mock_profile

    mock_result_user = MagicMock()
    mock_result_user.scalars().first.return_value = mock_user

    mock_db.execute.side_effect = [mock_result_user]

    response = client.get(f"/admin/users/{str(target_id)}")
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["id"] == str(target_id)
    assert res_data["email"] == "detail@example.com"
    assert res_data["profile"]["theme_preference"] == "luxury"

    clear_auth_overrides()


def test_get_user_detail_not_found():
    set_auth_overrides(admin_user)
    mock_db.reset_mock()

    mock_result_user = MagicMock()
    mock_result_user.scalars().first.return_value = None

    mock_db.execute.side_effect = [mock_result_user]

    response = client.get(f"/admin/users/{str(uuid4())}")
    assert response.status_code == 404
    assert response.json()["detail"] == "User not found"

    clear_auth_overrides()


def test_get_user_detail_invalid_uuid_blackbox():
    set_auth_overrides(admin_user)
    response = client.get("/admin/users/invalid-uuid-format-string")
    assert response.status_code == 422
    clear_auth_overrides()


def test_list_users_as_admin_role_filtering_whitebox():
    set_auth_overrides(admin_user)
    mock_db.reset_mock()

    mock_admin_user = MagicMock()
    mock_admin_user.id = uuid4()
    mock_admin_user.email = "admin2@example.com"
    mock_admin_user.created_at = "2026-07-27T00:00:00Z"

    mock_admin_profile = MagicMock()
    mock_admin_profile.username = "admin_user_2"
    mock_admin_profile.role = "admin"
    mock_admin_profile.display_name = "Admin User 2"
    mock_admin_profile.avatar_key = None
    mock_admin_profile.theme_preference = "luxury"
    mock_admin_profile.id = mock_admin_user.id
    mock_admin_profile.created_at = "2026-07-27T00:00:00Z"

    mock_admin_user.profile = mock_admin_profile

    mock_result_users = MagicMock()
    mock_result_users.scalars().unique.return_value.all.return_value = [mock_admin_user]

    mock_db.execute.side_effect = [mock_result_users]

    response = client.get("/admin/users?role=admin&limit=5")
    assert response.status_code == 200
    users = response.json()
    assert len(users) == 1
    assert users[0]["profile"]["role"] == "admin"

    clear_auth_overrides()
