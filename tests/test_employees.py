import pytest


@pytest.fixture
def sample_employee():
    return {
        "employee_code": "EMP001",
        "full_name": "John Doe",
        "email": "john@company.com",
        "phone": "+919876543210",
        "department": "Engineering",
        "designation": "Software Engineer",
        "date_of_joining": "2024-01-15",
        "basic_salary": 50000.00,
        "hra": 20000.00,
        "conveyance_allowance": 3000.00,
        "medical_allowance": 2500.00,
        "special_allowance": 5000.00,
        "pf_deduction": 6000.00,
        "professional_tax": 200.00,
        "tds": 5000.00,
        "esi": 0,
    }


def test_create_employee(client, auth_headers, sample_employee):
    response = client.post("/api/v1/employees/", json=sample_employee, headers=auth_headers)
    assert response.status_code == 201
    data = response.json()
    assert data["employee_code"] == "EMP001"
    assert data["full_name"] == "John Doe"
    assert data["basic_salary"] == 50000.00


def test_create_employee_duplicate_code(client, auth_headers, sample_employee):
    client.post("/api/v1/employees/", json=sample_employee, headers=auth_headers)
    response = client.post("/api/v1/employees/", json=sample_employee, headers=auth_headers)
    assert response.status_code == 409


def test_list_employees(client, auth_headers, sample_employee):
    client.post("/api/v1/employees/", json=sample_employee, headers=auth_headers)
    response = client.get("/api/v1/employees/", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert len(data["items"]) == 1


def test_get_employee(client, auth_headers, sample_employee):
    create_res = client.post("/api/v1/employees/", json=sample_employee, headers=auth_headers)
    emp_id = create_res.json()["id"]
    response = client.get(f"/api/v1/employees/{emp_id}", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["employee_code"] == "EMP001"


def test_update_employee(client, auth_headers, sample_employee):
    create_res = client.post("/api/v1/employees/", json=sample_employee, headers=auth_headers)
    emp_id = create_res.json()["id"]
    response = client.put(f"/api/v1/employees/{emp_id}", json={"full_name": "Jane Doe"}, headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["full_name"] == "Jane Doe"


def test_delete_employee(client, auth_headers, sample_employee):
    create_res = client.post("/api/v1/employees/", json=sample_employee, headers=auth_headers)
    emp_id = create_res.json()["id"]
    response = client.delete(f"/api/v1/employees/{emp_id}", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["is_active"] is False


def test_search_employees(client, auth_headers, sample_employee):
    client.post("/api/v1/employees/", json=sample_employee, headers=auth_headers)
    response = client.get("/api/v1/employees/?search=John", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["total"] == 1

    response = client.get("/api/v1/employees/?search=Nobody", headers=auth_headers)
    assert response.json()["total"] == 0


def test_employee_not_found(client, auth_headers):
    response = client.get("/api/v1/employees/9999", headers=auth_headers)
    assert response.status_code == 404


def test_employees_require_auth(client):
    response = client.get("/api/v1/employees/")
    assert response.status_code == 401
