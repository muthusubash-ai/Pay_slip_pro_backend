def test_register(client):
    response = client.post("/api/v1/auth/register", json={
        "email": "new@example.com",
        "password": "TestPassword123!",
        "full_name": "New User",
    })
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "new@example.com"
    assert data["full_name"] == "New User"


def test_register_duplicate_email(client):
    client.post("/api/v1/auth/register", json={
        "email": "dup@example.com",
        "password": "TestPassword123!",
        "full_name": "Dup User",
    })
    response = client.post("/api/v1/auth/register", json={
        "email": "dup@example.com",
        "password": "TestPassword123!",
        "full_name": "Dup User Two",
    })
    assert response.status_code == 409


def test_login(client):
    client.post("/api/v1/auth/register", json={
        "email": "login@example.com",
        "password": "TestPassword123!",
        "full_name": "Login User",
    })
    response = client.post("/api/v1/auth/login", data={
        "username": "login@example.com",
        "password": "TestPassword123!",
    })
    assert response.status_code == 200
    data = response.json()
    assert "access_token" not in data
    assert "refresh_token" not in data
    assert settings.AUTH_ACCESS_COOKIE_NAME in response.cookies
    assert settings.AUTH_REFRESH_COOKIE_NAME in response.cookies


def test_login_invalid_credentials(client):
    response = client.post("/api/v1/auth/login", data={
        "username": "wrong@example.com",
        "password": "wrongpass",
    })
    assert response.status_code == 401


def test_get_me(client, auth_headers):
    response = client.get("/api/v1/auth/me", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "test@example.com"


def test_update_profile(client, auth_headers):
    response = client.put("/api/v1/auth/me", json={"full_name": "Updated Name"}, headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["full_name"] == "Updated Name"


def test_update_profile_cannot_change_own_role(client, auth_headers):
    response = client.put(
        "/api/v1/auth/me",
        json={"full_name": "Updated Name", "role": "admin"},
        headers=auth_headers,
    )

    assert response.status_code == 400
    assert "role" in response.json()

    me_response = client.get("/api/v1/auth/me", headers=auth_headers)
    assert me_response.status_code == 200
    assert me_response.json()["role"] == "hr_manager"


def test_refresh_token(client):
    client.post("/api/v1/auth/register", json={
        "email": "refresh@example.com",
        "password": "TestPassword123!",
        "full_name": "Refresh User",
    })
    login_res = client.post("/api/v1/auth/login", data={
        "username": "refresh@example.com",
        "password": "TestPassword123!",
    })
    old_refresh = login_res.cookies[settings.AUTH_REFRESH_COOKIE_NAME].value
    response = client.post("/api/v1/auth/refresh", json={})
    assert response.status_code == 200
    assert "access_token" not in response.json()
    assert response.cookies[settings.AUTH_REFRESH_COOKIE_NAME].value != old_refresh


def test_protected_route_no_token(client):
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401


def test_health_check_remains_public(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
from django.conf import settings
