from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from app.api.deps import get_current_user, get_db
from app.main import app
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
regular_user = MagicMock()
regular_user.id = uuid4()
regular_user.email = "user@example.com"
regular_user.profile = MagicMock()
regular_user.profile.role = "user"
regular_user.profile.username = "regular_user"


# Helper to override authorization dependencies for testing specific roles
def set_auth_overrides(current_user):
    app.dependency_overrides[get_current_user] = lambda: current_user


def clear_auth_overrides():
    if get_current_user in app.dependency_overrides:
        del app.dependency_overrides[get_current_user]


# --------------------------------------------------------------------------------
def test_list_user_projects_authenticated_success():
    set_auth_overrides(regular_user)
    mock_db.reset_mock()

    mock_project = MagicMock()
    mock_project.id = uuid4()
    mock_project.user_id = regular_user.id
    mock_project.title = "Test Meeting"
    mock_project.status = "done"
    mock_project.duration_seconds = 120
    mock_project.started_at = "2026-07-27T01:00:00Z"
    mock_project.created_at = "2026-07-27T01:00:00Z"
    mock_project.updated_at = "2026-07-27T01:05:00Z"

    mock_result_projects = MagicMock()
    mock_result_projects.scalars().all.return_value = [mock_project]

    mock_db.execute.side_effect = [mock_result_projects]

    response = client.get("/projects")
    assert response.status_code == 200
    projects = response.json()
    assert len(projects) == 1
    assert projects[0]["title"] == "Test Meeting"
    assert projects[0]["status"] == "done"

    clear_auth_overrides()


def test_list_user_projects_unauthenticated():

    clear_auth_overrides()
    response = client.get("/projects")

    assert response.status_code in (401, 403)


def test_list_user_projects_invalid_auth_token_format_blackbox():

    clear_auth_overrides()
    headers = {"Authorization": "Bearer invalid.jwt.token"}
    response = client.get("/projects", headers=headers)

    assert response.status_code == 401
    assert "Could not validate credentials" in response.json()["detail"]


def test_list_user_projects_no_auth_header_blackbox():

    clear_auth_overrides()
    response = client.get("/projects")

    assert response.status_code in (401, 403)
