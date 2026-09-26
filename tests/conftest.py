import pytest
from rest_framework.test import APIClient


@pytest.fixture(autouse=True)
def enable_db_access(db):
    """Autouse fixture to enable database access for all tests."""
    pass


class CompatibleAPIClient(APIClient):
    def post(self, path, data=None, format=None, content_type=None, follow=False, **extra):
        if "json" in extra:
            data = extra.pop("json")
            format = "json"
        return super().post(path, data=data, format=format, content_type=content_type, follow=follow, **extra)

    def put(self, path, data=None, format=None, content_type=None, follow=False, **extra):
        if "json" in extra:
            data = extra.pop("json")
            format = "json"
        return super().put(path, data=data, format=format, content_type=content_type, follow=follow, **extra)

    def patch(self, path, data=None, format=None, content_type=None, follow=False, **extra):
        if "json" in extra:
            data = extra.pop("json")
            format = "json"
        return super().patch(path, data=data, format=format, content_type=content_type, follow=follow, **extra)


@pytest.fixture
def client():
    """Django REST Framework API Client."""
    return CompatibleAPIClient()


@pytest.fixture
def auth_headers(client):
    """Register and login a test user, returning the authorization bearer header."""
    client.post("/api/v1/auth/register", data={
        "email": "test@example.com",
        "password": "testpassword123",
        "full_name": "Test User",
    }, format="json")

    # Existing endpoint tests exercise the complete application. Individual
    # plan tests explicitly downgrade this account to validate restrictions.
    from app.models.user import User
    User.objects.filter(email="test@example.com").update(plan="enterprise")
    
    # login supports both username/email in request data
    response = client.post("/api/v1/auth/login", data={
        "username": "test@example.com",
        "password": "testpassword123",
    }, format="json")
    
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
