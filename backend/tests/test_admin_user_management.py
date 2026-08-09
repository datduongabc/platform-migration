import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from app.api.deps import get_current_admin, get_current_user, get_db
from app.main import app
from app.services.admin_guards import is_last_admin, is_self_action
from fastapi import HTTPException
from fastapi.testclient import TestClient

client = TestClient(app)
mock_db = MagicMock()
mock_db.execute = AsyncMock()
mock_db.commit = AsyncMock()


@pytest.fixture(autouse=True)
def setup_db():
    async def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    yield
    if get_db in app.dependency_overrides:
        del app.dependency_overrides[get_db]


admin_user = MagicMock()
admin_user.id = uuid4()
admin_user.email = "admin@example.com"
admin_user.profile = MagicMock()
admin_user.profile.role = "admin"
admin_user.profile.username = "admin_user"


def set_admin_auth():
    app.dependency_overrides[get_current_user] = lambda: admin_user
    app.dependency_overrides[get_current_admin] = lambda: admin_user


def clear_auth_overrides():
    if get_current_user in app.dependency_overrides:
        del app.dependency_overrides[get_current_user]
    if get_current_admin in app.dependency_overrides:
        del app.dependency_overrides[get_current_admin]


def make_user_with_profile(user_id, role="user"):
    user = MagicMock()
    user.id = user_id
    user.email = f"{user_id}@example.com"
    user.disabled_at = None
    user.created_at = "2026-07-27T00:00:00Z"
    user.profile = MagicMock()
    user.profile.role = role
    user.profile.username = "target_user"
    user.profile.display_name = None
    user.profile.avatar_key = None
    user.profile.theme_preference = "default"
    user.profile.id = user_id
    user.profile.created_at = "2026-07-27T00:00:00Z"
    return user


def count_result(n):
    r = MagicMock()
    r.scalar.return_value = n
    return r


def user_result(user):
    r = MagicMock()
    r.scalars.return_value.first.return_value = user
    return r


# --------------------------------------------------------------------------------
# Pure guard function tests (admin_guards.py) — no DB/HTTP needed.


def test_is_self_action_true_for_matching_ids():
    uid = uuid4()
    assert is_self_action(uid, uid) is True
    assert is_self_action(str(uid), str(uid)) is True


def test_is_self_action_false_for_different_ids():
    assert is_self_action(uuid4(), uuid4()) is False


def test_is_last_admin_false_for_non_admin_target():
    # Must short-circuit before touching the DB when the target isn't an admin.
    # Run via asyncio.run() directly rather than an async test function, since
    # this suite has no pytest-asyncio/anyio plugin configured anywhere else.
    result = asyncio.run(is_last_admin(mock_db, "user"))
    assert result is False


# --------------------------------------------------------------------------------
# PATCH /admin/users/{id}/role


def test_update_role_self_action_forbidden():
    set_admin_auth()
    mock_db.reset_mock()

    # The endpoint fetches the target user (here, the caller themselves) before
    # checking is_self_action, so that lookup must be mocked too.
    mock_db.execute.side_effect = [user_result(admin_user)]

    response = client.patch(
        f"/admin/users/{admin_user.id}/role", json={"role": "user"}
    )
    assert response.status_code == 403
    assert "own role" in response.json()["detail"]
    clear_auth_overrides()


def test_update_role_invalid_role_rejected():
    set_admin_auth()
    mock_db.reset_mock()

    response = client.patch(
        f"/admin/users/{uuid4()}/role", json={"role": "superadmin"}
    )
    assert response.status_code == 422
    clear_auth_overrides()


def test_update_role_last_admin_guard_blocks_demotion():
    set_admin_auth()
    mock_db.reset_mock()

    target_id = uuid4()
    target = make_user_with_profile(target_id, role="admin")

    mock_db.execute.side_effect = [
        user_result(target),  # get_by_id_with_profile
        count_result(1),  # is_last_admin count -> only 1 admin left
    ]

    response = client.patch(f"/admin/users/{target_id}/role", json={"role": "user"})
    assert response.status_code == 403
    assert "last remaining admin" in response.json()["detail"]
    clear_auth_overrides()


def test_update_role_promote_success():
    set_admin_auth()
    mock_db.reset_mock()

    target_id = uuid4()
    target = make_user_with_profile(target_id, role="user")
    refetched = make_user_with_profile(target_id, role="admin")

    # Promotion never checks is_last_admin (only demotions do).
    mock_db.execute.side_effect = [
        user_result(target),  # get_by_id_with_profile
        MagicMock(),  # write_audit_log INSERT
        user_result(refetched),  # refetch after commit
    ]

    response = client.patch(f"/admin/users/{target_id}/role", json={"role": "admin"})
    assert response.status_code == 200
    assert response.json()["profile"]["role"] == "admin"
    clear_auth_overrides()


def test_update_role_user_not_found():
    set_admin_auth()
    mock_db.reset_mock()

    mock_db.execute.side_effect = [user_result(None)]

    response = client.patch(f"/admin/users/{uuid4()}/role", json={"role": "admin"})
    assert response.status_code == 404
    clear_auth_overrides()


# --------------------------------------------------------------------------------
# PATCH /admin/users/{id}/status


def test_disable_self_forbidden():
    set_admin_auth()
    mock_db.reset_mock()

    mock_db.execute.side_effect = [user_result(admin_user)]

    response = client.patch(
        f"/admin/users/{admin_user.id}/status", json={"disabled": True}
    )
    assert response.status_code == 403
    assert "disable themselves" in response.json()["detail"]
    clear_auth_overrides()


def test_disable_last_admin_blocked():
    set_admin_auth()
    mock_db.reset_mock()

    target_id = uuid4()
    target = make_user_with_profile(target_id, role="admin")

    mock_db.execute.side_effect = [
        user_result(target),
        count_result(1),
    ]

    response = client.patch(
        f"/admin/users/{target_id}/status", json={"disabled": True}
    )
    assert response.status_code == 403
    assert "last remaining admin" in response.json()["detail"]
    clear_auth_overrides()


def test_enable_disabled_user_success():
    set_admin_auth()
    mock_db.reset_mock()

    target_id = uuid4()
    target = make_user_with_profile(target_id, role="user")
    refetched = make_user_with_profile(target_id, role="user")

    # Re-enabling (disabled=False) never checks is_last_admin — only disabling does.
    mock_db.execute.side_effect = [
        user_result(target),
        MagicMock(),  # write_audit_log INSERT
        user_result(refetched),
    ]

    response = client.patch(
        f"/admin/users/{target_id}/status", json={"disabled": False}
    )
    assert response.status_code == 200
    clear_auth_overrides()


# --------------------------------------------------------------------------------
# DELETE /admin/users/{id}


def test_delete_self_forbidden():
    set_admin_auth()
    mock_db.reset_mock()

    mock_db.execute.side_effect = [user_result(admin_user)]

    response = client.delete(f"/admin/users/{admin_user.id}")
    assert response.status_code == 403
    assert "delete themselves" in response.json()["detail"]
    clear_auth_overrides()


def test_delete_last_admin_blocked():
    set_admin_auth()
    mock_db.reset_mock()

    target_id = uuid4()
    target = make_user_with_profile(target_id, role="admin")

    mock_db.execute.side_effect = [
        user_result(target),
        count_result(1),
    ]

    response = client.delete(f"/admin/users/{target_id}")
    assert response.status_code == 403
    assert "last remaining admin" in response.json()["detail"]
    clear_auth_overrides()


def test_delete_regular_user_success():
    set_admin_auth()
    mock_db.reset_mock()
    mock_db.delete = AsyncMock()

    target_id = uuid4()
    target = make_user_with_profile(target_id, role="user")

    mock_db.execute.side_effect = [
        user_result(target),
        MagicMock(),  # write_audit_log INSERT
    ]

    response = client.delete(f"/admin/users/{target_id}")
    assert response.status_code == 200
    assert response.json()["ok"] is True
    clear_auth_overrides()


# --------------------------------------------------------------------------------
# POST /admin/users/{id}/reset-password


def test_reset_password_returns_temp_password_once():
    set_admin_auth()
    mock_db.reset_mock()

    target_id = uuid4()
    target = MagicMock()
    target.id = target_id

    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = target
    mock_db.execute.side_effect = [
        mock_result,  # get_by_id
        MagicMock(),  # write_audit_log INSERT
    ]

    response = client.post(f"/admin/users/{target_id}/reset-password")
    assert response.status_code == 200
    body = response.json()
    assert "temporaryPassword" in body
    assert len(body["temporaryPassword"]) >= 12
    clear_auth_overrides()


def test_reset_password_user_not_found():
    set_admin_auth()
    mock_db.reset_mock()

    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = None
    mock_db.execute.side_effect = [mock_result]

    response = client.post(f"/admin/users/{uuid4()}/reset-password")
    assert response.status_code == 404
    clear_auth_overrides()
