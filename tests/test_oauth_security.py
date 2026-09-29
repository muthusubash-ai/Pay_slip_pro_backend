from urllib.parse import parse_qs, urlparse

import pytest
from django.conf import settings
from rest_framework.test import APIClient

from app.auth.jwt_handler import token_digest
from app.exceptions import BadRequestError, UnauthorizedError
from app.models.refresh_token import RefreshToken
from app.services import auth_service, google_auth_service

PASSWORD = "SecurePassword123!"


def _register_and_login(client, email="secure@example.com"):
    client.post(
        "/api/v1/auth/register",
        data={"email": email, "password": PASSWORD, "full_name": "Secure User"},
        format="json",
    )
    return client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": PASSWORD},
        format="json",
    )


def test_login_tokens_are_http_only_cookies_and_refresh_is_hashed(client):
    response = _register_and_login(client)

    assert response.status_code == 200
    assert "access_token" not in response.json()
    assert "refresh_token" not in response.json()

    access_cookie = response.cookies[settings.AUTH_ACCESS_COOKIE_NAME]
    refresh_cookie = response.cookies[settings.AUTH_REFRESH_COOKIE_NAME]
    assert access_cookie["httponly"] is True
    assert refresh_cookie["httponly"] is True
    assert access_cookie["samesite"] == "Lax"
    assert refresh_cookie["samesite"] == "Lax"
    assert RefreshToken.objects.get().token == token_digest(refresh_cookie.value)
    assert refresh_cookie.value not in RefreshToken.objects.get().token


def test_cookie_authenticated_mutation_requires_csrf():
    client = APIClient(enforce_csrf_checks=True)
    csrf_response = client.get("/api/v1/auth/csrf")
    csrf_token = csrf_response.json()["csrf_token"]

    client.post(
        "/api/v1/auth/register",
        data={"email": "csrf@example.com", "password": PASSWORD, "full_name": "CSRF User"},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_token,
    )
    login_response = client.post(
        "/api/v1/auth/login",
        data={"username": "csrf@example.com", "password": PASSWORD},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_token,
    )
    assert login_response.status_code == 200

    rejected = client.put(
        "/api/v1/auth/me",
        data={"full_name": "Rejected"},
        format="json",
    )
    accepted = client.put(
        "/api/v1/auth/me",
        data={"full_name": "Accepted"},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_token,
    )

    assert rejected.status_code == 403
    assert accepted.status_code == 200


def test_google_login_uses_state_pkce_and_http_only_binding(client, settings):
    settings.GOOGLE_CLIENT_ID = "google-client"
    settings.GOOGLE_CLIENT_SECRET = "google-secret"

    response = client.get("/api/v1/auth/google/login")
    query = parse_qs(urlparse(response["Location"]).query)

    assert response.status_code == 302
    assert query["state"][0]
    assert query["code_challenge"][0]
    assert query["code_challenge_method"] == ["S256"]
    assert query["access_type"] == ["online"]
    state_cookie = response.cookies[settings.GOOGLE_OAUTH_STATE_COOKIE_NAME]
    assert state_cookie.value == query["state"][0]
    assert state_cookie["httponly"] is True


def test_google_callback_never_places_tokens_in_redirect_url(client, settings, monkeypatch):
    settings.GOOGLE_CLIENT_ID = "google-client"
    settings.GOOGLE_CLIENT_SECRET = "google-secret"
    settings.FRONTEND_URL = "https://app.example.com"

    login_response = client.get("/api/v1/auth/google/login")
    state = parse_qs(urlparse(login_response["Location"]).query)["state"][0]

    async def fake_exchange(code, code_verifier):
        assert code == "authorization-code"
        assert code_verifier
        return {"access_token": "google-access-token"}

    async def fake_user_info(access_token):
        assert access_token == "google-access-token"
        return {
            "id": "google-123",
            "email": "oauth@example.com",
            "verified_email": True,
            "name": "OAuth User",
        }

    monkeypatch.setattr(google_auth_service, "exchange_code_for_tokens", fake_exchange)
    monkeypatch.setattr(google_auth_service, "get_google_user_info", fake_user_info)

    response = client.get(
        f"/api/v1/auth/google/callback?code=authorization-code&state={state}"
    )

    assert response.status_code == 302
    assert response["Location"] == "https://app.example.com/auth/google/callback"
    assert "token" not in response["Location"]
    assert response.cookies[settings.AUTH_ACCESS_COOKIE_NAME]["httponly"] is True
    assert response.cookies[settings.AUTH_REFRESH_COOKIE_NAME]["httponly"] is True


def test_google_state_is_browser_bound_and_one_time(client, settings):
    settings.GOOGLE_CLIENT_ID = "google-client"
    settings.GOOGLE_CLIENT_SECRET = "google-secret"
    _, state = google_auth_service.create_google_login_request()

    with pytest.raises(BadRequestError):
        google_auth_service.consume_google_oauth_state(state, "wrong-browser-state")

    verifier = google_auth_service.consume_google_oauth_state(state, state)
    assert verifier
    with pytest.raises(BadRequestError):
        google_auth_service.consume_google_oauth_state(state, state)


def test_unverified_google_email_is_rejected():
    with pytest.raises(UnauthorizedError):
        google_auth_service.get_or_create_google_user(
            None,
            {"id": "google-123", "email": "unverified@example.com", "verified_email": False},
        )


def test_refresh_rotation_detects_reuse_and_revokes_token_family(client):
    login_response = _register_and_login(client, "rotation@example.com")
    first_refresh = login_response.cookies[settings.AUTH_REFRESH_COOKIE_NAME].value
    original_expiry = RefreshToken.objects.get(token=token_digest(first_refresh)).expires_at

    refresh_response = client.post("/api/v1/auth/refresh", data={}, format="json")
    assert refresh_response.status_code == 200
    second_refresh = refresh_response.cookies[settings.AUTH_REFRESH_COOKIE_NAME].value
    rotated_record = RefreshToken.objects.get(token=token_digest(second_refresh))
    assert rotated_record.expires_at == original_expiry

    with pytest.raises(UnauthorizedError, match="reuse detected"):
        auth_service.refresh_tokens(None, first_refresh)
    with pytest.raises(UnauthorizedError):
        auth_service.refresh_tokens(None, second_refresh)

    assert not RefreshToken.objects.filter(revoked=False).exists()


def test_refresh_still_works_when_access_cookie_is_expired_or_invalid(client):
    _register_and_login(client, "expired-access@example.com")
    client.cookies[settings.AUTH_ACCESS_COOKIE_NAME] = "expired-access-token"

    response = client.post("/api/v1/auth/refresh", data={}, format="json")

    assert response.status_code == 200
    assert settings.AUTH_ACCESS_COOKIE_NAME in response.cookies
