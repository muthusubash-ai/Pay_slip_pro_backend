def test_register(client):
    response = client.post("/api/v1/auth/register", json={
        "email": "new@example.com",
        "password": "password123",
        "full_name": "New User",
    })
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "new@example.com"
    assert data["full_name"] == "New User"


def test_register_duplicate_email(client):
    client.post("/api/v1/auth/register", json={
        "email": "dup@example.com",
        "password": "password123",
        "full_name": "Dup User",
    })
    response = client.post("/api/v1/auth/register", json={
        "email": "dup@example.com",
        "password": "password123",
        "full_name": "Dup User 2",
    })
    assert response.status_code == 409


def test_login(client):
    client.post("/api/v1/auth/register", json={
        "email": "login@example.com",
        "password": "password123",
        "full_name": "Login User",
    })
    response = client.post("/api/v1/auth/login", data={
        "username": "login@example.com",
        "password": "password123",
    })
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


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


def test_refresh_token(client):
    client.post("/api/v1/auth/register", json={
        "email": "refresh@example.com",
        "password": "password123",
        "full_name": "Refresh User",
    })
    login_res = client.post("/api/v1/auth/login", data={
        "username": "refresh@example.com",
        "password": "password123",
    })
    refresh_token = login_res.json()["refresh_token"]
    response = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert response.status_code == 200
    assert "access_token" in response.json()


def test_protected_route_no_token(client):
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401
