from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from app.api.deps import get_current_user, get_db
from app.main import app
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


current_user = MagicMock()
current_user.id = uuid4()
current_user.email = "user@example.com"


def set_auth():
    app.dependency_overrides[get_current_user] = lambda: current_user


def clear_auth():
    if get_current_user in app.dependency_overrides:
        del app.dependency_overrides[get_current_user]


def profile_result(profile):
    r = MagicMock()
    r.scalars.return_value.first.return_value = profile
    return r


def empty_settings_result():
    # load_generation_config falls back to DEFAULT_ALLOWED_MODELS when
    # app_settings has no seeded rows — this is exactly the "empty" case.
    r = MagicMock()
    r.fetchall.return_value = []
    return r


def make_profile(default_provider=None, default_model=None):
    p = MagicMock()
    p.default_provider = default_provider
    p.default_model = default_model
    return p


def test_get_preferences_falls_back_to_default_allowed_models():
    set_auth()
    mock_db.reset_mock()

    profile = make_profile()
    mock_db.execute.side_effect = [profile_result(profile), empty_settings_result()]

    response = client.get("/profile/preferences")
    assert response.status_code == 200
    body = response.json()
    assert body["provider"] is None
    assert body["model"] is None
    # Both registry-backed defaults should be visible when nothing is seeded yet.
    assert {"provider": "gemini", "model": "gemini-3.5-flash-lite"} in body["allowedModels"]
    assert {"provider": "gemini", "model": "gemini-3.5-flash"} in body["allowedModels"]
    clear_auth()


def test_get_preferences_profile_not_found():
    set_auth()
    mock_db.reset_mock()
    mock_db.execute.side_effect = [profile_result(None)]

    response = client.get("/profile/preferences")
    assert response.status_code == 404
    clear_auth()


def test_patch_preferences_clears_when_both_null():
    set_auth()
    mock_db.reset_mock()

    profile = make_profile("gemini", "gemini-3.5-flash-lite")
    mock_db.execute.side_effect = [profile_result(profile)]

    response = client.patch(
        "/profile/preferences", json={"provider": None, "model": None}
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True, "provider": None, "model": None}
    assert profile.default_provider is None
    assert profile.default_model is None
    clear_auth()


def test_patch_preferences_rejects_partial_provider_only():
    set_auth()
    mock_db.reset_mock()

    profile = make_profile()
    mock_db.execute.side_effect = [profile_result(profile)]

    response = client.patch("/profile/preferences", json={"provider": "gemini"})
    assert response.status_code == 400
    assert "both" in response.json()["detail"]
    clear_auth()


def test_patch_preferences_rejects_disallowed_model():
    set_auth()
    mock_db.reset_mock()

    profile = make_profile()
    mock_db.execute.side_effect = [profile_result(profile), empty_settings_result()]

    response = client.patch(
        "/profile/preferences",
        json={"provider": "openai", "model": "gpt-4o"},
    )
    assert response.status_code == 400
    assert "not currently allowed" in response.json()["detail"]
    clear_auth()


def test_patch_preferences_accepts_allowed_model():
    set_auth()
    mock_db.reset_mock()

    profile = make_profile()
    mock_db.execute.side_effect = [profile_result(profile), empty_settings_result()]

    response = client.patch(
        "/profile/preferences",
        json={"provider": "gemini", "model": "gemini-3.5-flash"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body == {"ok": True, "provider": "gemini", "model": "gemini-3.5-flash"}
    assert profile.default_provider == "gemini"
    assert profile.default_model == "gemini-3.5-flash"
    clear_auth()
