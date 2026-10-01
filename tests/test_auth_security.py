from django.core.cache import cache
from django.conf import settings

from app.models.refresh_token import RefreshToken
from app.models.user import User, UserRole
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


def test_password_reset_invalidates_access_and_refresh_sessions(client):
    email = "session-reset@example.com"
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": STRONG_PASSWORD, "full_name": "Session Reset"},
    )
    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": STRONG_PASSWORD},
    )
    assert login.status_code == 200
    old_access = login.cookies[settings.AUTH_ACCESS_COOKIE_NAME].value
    old_refresh = login.cookies[settings.AUTH_REFRESH_COOKIE_NAME].value
    cache.set(
        auth_service._reset_code_cache_key(email),
        auth_service._reset_code_digest("123456"),
        timeout=auth_service.RESET_CODE_TTL_SECONDS,
    )

    reset = client.post(
        "/api/v1/auth/reset-password",
        json={"email": email, "token": "123456", "new_password": "NewSecurePassword123!"},
    )
    assert reset.status_code == 200
    assert client.get("/api/v1/auth/me", HTTP_AUTHORIZATION=f"Bearer {old_access}").status_code in (401, 403)
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh}).status_code == 401
    assert not RefreshToken.objects.filter(user__email=email, revoked=False).exists()
    assert client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "NewSecurePassword123!"},
    ).status_code == 200


def test_registration_is_rate_limited_per_email(client):
    responses = [
        client.post(
            "/api/v1/auth/register",
            json={
                "email": "register-limit@example.com",
                "password": "weak",
                "full_name": "Register Limit",
            },
        )
        for _ in range(4)
    ]
    assert all(response.status_code == 400 for response in responses[:3])
    assert responses[3].status_code == 429


def test_salary_slip_email_is_rate_limited_per_user(client, auth_headers, monkeypatch):
    from app.auth.throttles import EmailSlipRateThrottle

    monkeypatch.setattr(EmailSlipRateThrottle, "get_rate", lambda self: "2/min")
    responses = [
        client.post("/api/v1/salary-slips/999/email", headers=auth_headers)
        for _ in range(3)
    ]
    assert all(response.status_code == 404 for response in responses[:2])
    assert responses[2].status_code == 429


def test_customer_admin_cannot_access_platform_users(client):
    customer_admin = User.objects.create_user(
        email="customer-admin@example.com",
        password=STRONG_PASSWORD,
        full_name="Customer Admin",
        role=UserRole.admin,
        plan="enterprise",
    )
    another_customer = User.objects.create_user(
        email="another-customer@example.com",
        password=STRONG_PASSWORD,
        full_name="Another Customer",
        plan="enterprise",
    )
    assert not customer_admin.is_staff
    assert not customer_admin.is_superuser
    client.force_authenticate(user=customer_admin)
    assert client.get("/api/v1/admin/users").status_code == 403
    assert client.get("/api/v1/admin/stats").status_code == 403
    assert client.put(
        f"/api/v1/admin/users/{another_customer.id}", json={"role": "admin"}
    ).status_code == 403


def test_explicit_platform_admin_can_access_platform_users(client):
    platform_admin = User.objects.create_superuser(
        email="platform-owner@example.com",
        password=STRONG_PASSWORD,
        full_name="Platform Owner",
    )
    assert platform_admin.is_staff
    assert platform_admin.is_superuser
    client.force_authenticate(user=platform_admin)
    assert client.get("/api/v1/admin/users").status_code == 200
