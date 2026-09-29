from django.core.cache import cache

from app.models.user import User
from app.services import auth_service


STRONG_PASSWORD = "SecurePassword123!"


def test_registration_rejects_weak_password(client):
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "weak@example.com",
            "password": "password123",
            "full_name": "Weak Password",
        },
    )
    assert response.status_code == 400
    assert not User.objects.filter(email="weak@example.com").exists()


def test_password_reset_rejects_weak_password(client):
    client.post(
        "/api/v1/auth/register",
        json={
            "email": "reset@example.com",
            "password": STRONG_PASSWORD,
            "full_name": "Reset User",
        },
    )
    cache.set(
        auth_service._reset_code_cache_key("reset@example.com"),
        auth_service._reset_code_digest("123456"),
        timeout=auth_service.RESET_CODE_TTL_SECONDS,
    )
    response = client.post(
        "/api/v1/auth/reset-password",
        json={
            "email": "reset@example.com",
            "token": "123456",
            "new_password": "short",
        },
    )
    assert response.status_code == 400
    assert "12 characters" in response.json()["detail"]


def test_login_is_rate_limited_per_account(client):
    client.post(
        "/api/v1/auth/register",
        json={
            "email": "limited@example.com",
            "password": STRONG_PASSWORD,
            "full_name": "Limited User",
        },
    )
    responses = [
        client.post(
            "/api/v1/auth/login",
            json={"email": "limited@example.com", "password": "WrongPassword123!"},
        )
        for _ in range(6)
    ]
    assert all(response.status_code == 401 for response in responses[:5])
    assert responses[5].status_code == 429


def test_password_reset_request_is_rate_limited_per_account(client):
    responses = [
        client.post(
            "/api/v1/auth/forgot-password",
            json={"email": "unknown@example.com"},
        )
        for _ in range(4)
    ]
    assert all(response.status_code == 200 for response in responses[:3])
    assert responses[3].status_code == 429


def test_password_reset_verification_is_rate_limited_per_account(client):
    responses = [
        client.post(
            "/api/v1/auth/reset-password",
            json={
                "email": "unknown@example.com",
                "token": "000000",
                "new_password": STRONG_PASSWORD,
            },
        )
        for _ in range(6)
    ]
    assert all(response.status_code == 400 for response in responses[:5])
    assert responses[5].status_code == 429
