from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.api.deps import get_db
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_password_hash,
)
from app.main import app
from fastapi.testclient import TestClient

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


# Hepler functions


def test_password_hashing():
    raw_password = "mysecretpassword"
    hashed = get_password_hash(raw_password)
    assert hashed != raw_password
    assert hashed.startswith("$2b$")


def test_token_creation_and_decoding():
    token = create_access_token("user-123", expires_delta=timedelta(minutes=15))
    decoded = decode_token(token)
    assert decoded is not None
    assert decoded["sub"] == "user-123"
    assert decoded["type"] == "access"


def test_refresh_token_creation_and_decoding():
    token = create_refresh_token("user-123", expires_delta=timedelta(days=7))
    decoded = decode_token(token)
    assert decoded is not None
    assert decoded["sub"] == "user-123"
    assert decoded["type"] == "refresh"


def test_expired_token():
    token = create_access_token("user-123", expires_delta=timedelta(minutes=-5))
    decoded = decode_token(token)
    assert decoded is None


# Register


def test_register_endpoint_success():
    mock_db.reset_mock()

    # Mock email check and username check to return None (no conflict)
    mock_result_email = MagicMock()
    mock_result_email.scalars().first.return_value = None

    mock_result_username = MagicMock()
    mock_result_username.scalars().first.return_value = None

    mock_db.execute.side_effect = [mock_result_email, mock_result_username]

    payload = {
        "email": "testregister@example.com",
        "username": "testregister",
        "password": "strongpassword123",
    }

    response = client.post("/auth/register", json=payload)
    assert response.status_code == 201
    assert response.json()["message"] == "Account created successfully."


def test_register_email_already_exists():
    mock_db.reset_mock()

    mock_existing_user = MagicMock()
    mock_result_email = MagicMock()
    mock_result_email.scalars().first.return_value = mock_existing_user

    mock_result_username = MagicMock()
    mock_result_username.scalars().first.return_value = None
    mock_db.execute.side_effect = [mock_result_email, mock_result_username]

    payload = {
        "email": "existing@example.com",
        "username": "newuser",
        "password": "strongpassword123",
    }

    response = client.post("/auth/register", json=payload)
    assert response.status_code == 409
    assert "Email already exists" in response.json()["detail"]


def test_register_username_already_exists():

    mock_db.reset_mock()

    mock_result_email = MagicMock()
    mock_result_email.scalars().first.return_value = None

    mock_existing_profile = MagicMock()
    mock_result_username = MagicMock()
    mock_result_username.scalars().first.return_value = mock_existing_profile

    mock_db.execute.side_effect = [mock_result_email, mock_result_username]

    payload = {
        "email": "newuser@example.com",
        "username": "existinguser",
        "password": "strongpassword123",
    }

    response = client.post("/auth/register", json=payload)
    assert response.status_code == 409
    assert "Username already exists" in response.json()["detail"]


def test_register_invalid_inputs_blackbox():
    payload = {
        "email": "invalid-email-format",
        "username": "us",
        "password": "123",
    }

    response = client.post("/auth/register", json=payload)
    assert response.status_code == 422


# Login


def test_login_endpoint_success():

    mock_db.reset_mock()

    mock_user = MagicMock()
    mock_user.id = "user-id-123"
    mock_user.email = "testlogin@example.com"
    mock_user.encrypted_password = get_password_hash("strongpassword123")

    mock_profile = MagicMock()
    mock_profile.id = "user-id-123"
    mock_profile.username = "testlogin"
    mock_profile.role = "user"

    mock_user.profile = mock_profile

    mock_result_user = MagicMock()
    mock_result_user.scalars().first.return_value = mock_user

    mock_db.execute.side_effect = [mock_result_user]

    payload = {"identifier": "testlogin@example.com", "password": "strongpassword123"}

    response = client.post("/auth/login", json=payload)
    assert response.status_code == 200
    res_data = response.json()
    assert "access_token" in res_data
    assert "refresh_token" in res_data
    assert res_data["user_id"] == "user-id-123"
    assert res_data["email"] == "testlogin@example.com"


def test_login_with_username_whitebox():
    mock_db.reset_mock()

    mock_user = MagicMock()
    mock_user.id = "user-id-456"
    mock_user.email = "testuser@example.com"
    mock_user.encrypted_password = get_password_hash("password12345")

    mock_profile = MagicMock()
    mock_profile.id = "user-id-456"
    mock_profile.username = "testusernameonly"
    mock_profile.role = "user"

    mock_user.profile = mock_profile

    mock_result_user = MagicMock()
    mock_result_user.scalars().first.return_value = mock_user

    mock_db.execute.side_effect = [
        mock_result_user,
    ]

    payload = {"identifier": "testusernameonly", "password": "password12345"}

    response = client.post("/auth/login", json=payload)
    assert response.status_code == 200
    assert response.json()["user_id"] == "user-id-456"


def test_login_user_not_found():
    mock_db.reset_mock()

    mock_result_user = MagicMock()
    mock_result_user.scalars().first.return_value = None

    mock_db.execute.side_effect = [mock_result_user]

    payload = {"identifier": "nonexistent@example.com", "password": "password123"}

    response = client.post("/auth/login", json=payload)
    assert response.status_code == 401
    assert "Invalid credentials" in response.json()["detail"]


def test_login_incorrect_password():
    mock_db.reset_mock()

    mock_user = MagicMock()
    mock_user.id = "user-id-123"
    mock_user.email = "testlogin@example.com"
    mock_user.encrypted_password = get_password_hash("strongpassword123")

    mock_profile = MagicMock()
    mock_profile.id = "user-id-123"
    mock_profile.username = "testlogin"
    mock_profile.role = "user"

    mock_user.profile = mock_profile

    mock_result_user = MagicMock()
    mock_result_user.scalars().first.return_value = mock_user

    mock_db.execute.side_effect = [mock_result_user]

    payload = {"identifier": "testlogin@example.com", "password": "wrongpassword"}

    response = client.post("/auth/login", json=payload)
    assert response.status_code == 401
    assert "Invalid credentials" in response.json()["detail"]


def test_login_sets_httponly_cookies():
    mock_db.reset_mock()

    mock_user = MagicMock()
    mock_user.id = "user-id-cookie"
    mock_user.email = "cookie@example.com"
    mock_user.encrypted_password = get_password_hash("cookiepassword")

    mock_profile = MagicMock()
    mock_profile.id = "user-id-cookie"
    mock_profile.username = "cookieuser"
    mock_profile.role = "user"
    mock_user.profile = mock_profile

    mock_result_user = MagicMock()
    mock_result_user.scalars().first.return_value = mock_user
    mock_db.execute.side_effect = [mock_result_user]

    response = client.post(
        "/auth/login",
        json={"identifier": "cookie@example.com", "password": "cookiepassword"},
    )
    assert response.status_code == 200
    assert "access_token" in response.cookies
    assert "refresh_token" in response.cookies


def test_logout_deletes_cookies():
    response = client.post("/auth/logout")
    assert response.status_code == 200
    assert response.json()["message"] == "Logged out successfully."
    # Fastapi delete_cookie sets cookie value to empty with max-age=0 / expires in past
    assert (
        response.cookies.get("access_token") is None
        or response.cookies.get("access_token") == ""
    )
