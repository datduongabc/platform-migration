from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

# Pre-emptively mock create_async_engine to prevent database connection checks during import
with patch("sqlalchemy.ext.asyncio.create_async_engine"):
    from app.api.deps import get_db
    from app.core.security import get_password_hash
    from app.main import app

client = TestClient(app)
mock_db = MagicMock()
mock_db.execute = AsyncMock()
mock_db.flush = AsyncMock()
mock_db.commit = AsyncMock()


@pytest.fixture(autouse=True)
def setup_db():
    async def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    yield
    if get_db in app.dependency_overrides:
        del app.dependency_overrides[get_db]


# ── E2E Integration Flow Test ────────────────────────────────────────────────


def test_e2e_user_journey_flow():
    mock_db.reset_mock()

    regular_id = uuid4()
    admin_id = uuid4()
    project_id = uuid4()

    # User Mocks
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)

    regular_user = MagicMock()
    regular_user.id = regular_id
    regular_user.email = "regular@example.com"
    regular_user.encrypted_password = get_password_hash("password123")
    regular_user.created_at = now

    regular_profile = MagicMock()
    regular_profile.id = regular_id
    regular_profile.username = "regular_user"
    regular_profile.role = "user"
    regular_profile.display_name = "Regular User"
    regular_profile.avatar_key = None
    regular_profile.theme_preference = "default"

    admin_user = MagicMock()
    admin_user.id = admin_id
    admin_user.email = "admin@example.com"
    admin_user.encrypted_password = get_password_hash("adminpassword123")
    admin_user.created_at = now

    admin_profile = MagicMock()
    admin_profile.id = admin_id
    admin_profile.username = "admin_user"
    admin_profile.role = "admin"
    admin_profile.display_name = "Admin User"
    admin_profile.avatar_key = None
    admin_profile.theme_preference = "luxury"

    # Project Mock
    mock_project = MagicMock()
    mock_project.id = project_id
    mock_project.user_id = regular_id
    mock_project.title = "E2E Meeting"
    mock_project.status = "done"
    mock_project.duration_seconds = 360
    mock_project.started_at = "2026-07-27T01:00:00Z"
    mock_project.created_at = "2026-07-27T01:00:00Z"
    mock_project.updated_at = "2026-07-27T01:06:00Z"

    # ──────────────────────────────────────────────────────────────────────────
    # DB Queries Sequence Mocking:
    # ──────────────────────────────────────────────────────────────────────────
    # Step 1: Register regular user
    mock_reg_email = MagicMock()
    mock_reg_email.scalars().first.return_value = None  # no email conflict
    mock_reg_user = MagicMock()
    mock_reg_user.scalars().first.return_value = None  # no username conflict

    # Step 2: Login as regular user
    mock_login_user = MagicMock()
    mock_login_user.scalars().first.return_value = regular_user
    mock_login_profile = MagicMock()
    mock_login_profile.scalars().first.return_value = regular_profile

    # Step 3: Fetch projects (calls get_current_user, then list_user_projects)
    mock_proj_auth_user = MagicMock()
    mock_proj_auth_user.scalars().first.return_value = regular_user
    mock_proj_auth_profile = MagicMock()
    mock_proj_auth_profile.scalars().first.return_value = regular_profile
    mock_proj_list = MagicMock()
    mock_proj_list.scalars().all.return_value = [mock_project]

    # Step 4: Access admin panel as regular user (calls get_current_user, then fails 403)
    mock_admin_fail_user = MagicMock()
    mock_admin_fail_user.scalars().first.return_value = regular_user
    mock_admin_fail_profile = MagicMock()
    mock_admin_fail_profile.scalars().first.return_value = regular_profile

    # Step 5: Login as admin
    mock_admin_login_user = MagicMock()
    mock_admin_login_user.scalars().first.return_value = admin_user
    mock_admin_login_profile = MagicMock()
    mock_admin_login_profile.scalars().first.return_value = admin_profile

    # Step 6: Access admin panel as admin (calls get_current_user, list_users, then gets user profile)
    mock_admin_auth_user = MagicMock()
    mock_admin_auth_user.scalars().first.return_value = admin_user
    mock_admin_auth_profile = MagicMock()
    mock_admin_auth_profile.scalars().first.return_value = admin_profile
    mock_admin_list_users = MagicMock()
    mock_admin_list_users.scalars().all.return_value = [regular_user]
    mock_admin_fetch_reg_profile = MagicMock()
    mock_admin_fetch_reg_profile.scalars().first.return_value = regular_profile

    # Apply mock execution side effects sequence
    mock_db.execute.side_effect = [
        # 1. Register regular user
        mock_reg_email,
        mock_reg_user,
        # 2. Login as regular user
        mock_login_user,
        mock_login_profile,
        # 3. Fetch projects
        mock_proj_auth_user,
        mock_proj_auth_profile,
        mock_proj_list,
        # 4. Access admin panel as regular user (fails before list)
        mock_admin_fail_user,
        mock_admin_fail_profile,
        # 5. Login as admin
        mock_admin_login_user,
        mock_admin_login_profile,
        # 6. Access admin panel as admin
        mock_admin_auth_user,
        mock_admin_auth_profile,
        mock_admin_list_users,
        mock_admin_fetch_reg_profile,
    ]

    # ──────────────────────────────────────────────────────────────────────────
    # Execution: E2E HTTP Requests flow
    # ──────────────────────────────────────────────────────────────────────────

    # 1. Register regular user
    reg_response = client.post(
        "/auth/register",
        json={
            "email": "regular@example.com",
            "username": "regular_user",
            "password": "password123",
        },
    )
    assert reg_response.status_code == 201

    # 2. Login as regular user
    login_response = client.post(
        "/auth/login",
        json={"identifier": "regular@example.com", "password": "password123"},
    )
    assert login_response.status_code == 200
    regular_tokens = login_response.json()
    assert "access_token" in regular_tokens
    assert regular_tokens["role"] == "user"

    # 3. Fetch Projects
    projects_headers = {"Authorization": f"Bearer {regular_tokens['access_token']}"}
    projects_response = client.get("/projects", headers=projects_headers)
    assert projects_response.status_code == 200
    projects = projects_response.json()
    assert len(projects) == 1
    assert projects[0]["title"] == "E2E Meeting"

    # 4. Try accessing admin panel as regular user (should get 403 Forbidden)
    admin_response = client.get("/admin/users", headers=projects_headers)
    assert admin_response.status_code == 403
    assert admin_response.json()["detail"] == "Not enough privileges"

    # 5. Login as admin
    admin_login_response = client.post(
        "/auth/login",
        json={"identifier": "admin@example.com", "password": "adminpassword123"},
    )
    assert admin_login_response.status_code == 200
    admin_tokens = admin_login_response.json()
    assert "access_token" in admin_tokens
    assert admin_tokens["role"] == "admin"

    # 6. Access admin panel as admin (should get 200 OK)
    admin_headers = {"Authorization": f"Bearer {admin_tokens['access_token']}"}
    admin_users_response = client.get("/admin/users", headers=admin_headers)
    assert admin_users_response.status_code == 200
    users_list = admin_users_response.json()
    assert len(users_list) == 1
    assert users_list[0]["email"] == "regular@example.com"
    assert users_list[0]["profile"]["username"] == "regular_user"

    # 7. Logout
    logout_response = client.post("/auth/logout", headers=admin_headers)
    assert logout_response.status_code == 200
    assert logout_response.json()["message"] == "Logged out successfully."
