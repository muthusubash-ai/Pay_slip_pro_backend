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


def test_list_employees_newest_first_and_alphabetical_sorting(client, auth_headers, sample_employee):
    # Create employee 1: "Zachary Adams" (Z)
    emp1 = sample_employee.copy()
    emp1["employee_code"] = "EMP001"
    emp1["full_name"] = "Zachary Adams"
    emp1["email"] = "zachary@example.com"
    client.post("/api/v1/employees/", json=emp1, headers=auth_headers)

    # Create employee 2: "Alice Brown" (A) - newly saved
    emp2 = sample_employee.copy()
    emp2["employee_code"] = "EMP002"
    emp2["full_name"] = "Alice Brown"
    emp2["email"] = "alice@example.com"
    client.post("/api/v1/employees/", json=emp2, headers=auth_headers)

    # 1. Default: newest saved employee should show at the TOP
    res_default = client.get("/api/v1/employees/", headers=auth_headers)
    assert res_default.status_code == 200
    names_default = [e["full_name"] for e in res_default.json()["items"]]
    assert names_default == ["Alice Brown", "Zachary Adams"]

    # 2. Alphabetical Ascending: A -> Z
    res_asc = client.get("/api/v1/employees/?sort=name_asc", headers=auth_headers)
    assert res_asc.status_code == 200
    names_asc = [e["full_name"] for e in res_asc.json()["items"]]
    assert names_asc == ["Alice Brown", "Zachary Adams"]

    # 3. Alphabetical Descending: Z -> A
    res_desc = client.get("/api/v1/employees/?sort=name_desc", headers=auth_headers)
    assert res_desc.status_code == 200
    names_desc = [e["full_name"] for e in res_desc.json()["items"]]
    assert names_desc == ["Zachary Adams", "Alice Brown"]


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


def test_create_employee_with_optional_shift_timing(client, auth_headers, sample_employee):
    payload = {**sample_employee, "shift_start_time": "09:30", "shift_end_time": "17:00"}
    response = client.post("/api/v1/employees/", json=payload, headers=auth_headers)
    assert response.status_code == 201
    data = response.json()
    assert data["shift_start_time"] == "09:30"
    assert data["shift_end_time"] == "17:00"


def test_create_employee_without_shift_timing_leaves_it_unset(client, auth_headers, sample_employee):
    response = client.post("/api/v1/employees/", json=sample_employee, headers=auth_headers)
    assert response.status_code == 201
    data = response.json()
    assert data["shift_start_time"] is None
    assert data["shift_end_time"] is None


def test_create_employee_rejects_invalid_shift_time_format(client, auth_headers, sample_employee):
    payload = {**sample_employee, "shift_start_time": "9:30 AM"}
    response = client.post("/api/v1/employees/", json=payload, headers=auth_headers)
    assert response.status_code == 400


def test_update_employee_shift_timing(client, auth_headers, sample_employee):
    create_res = client.post("/api/v1/employees/", json=sample_employee, headers=auth_headers)
    emp_id = create_res.json()["id"]
    response = client.put(
        f"/api/v1/employees/{emp_id}",
        json={"shift_start_time": "10:00", "shift_end_time": "17:30"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["shift_start_time"] == "10:00"
    assert response.json()["shift_end_time"] == "17:30"


def test_edit_joining_date_updates_attendance_eligibility(client, auth_headers, sample_employee):
    employee_id = client.post("/api/v1/employees/", json=sample_employee, headers=auth_headers).json()["id"]
    saved = client.post(
        "/api/v1/attendance/bulk",
        json={"employee_id": employee_id, "month": 1, "year": 2026, "leave_dates": []},
        headers=auth_headers,
    )
    assert saved.status_code == 201

    updated = client.put(
        f"/api/v1/employees/{employee_id}",
        json={"date_of_joining": "2026-03-15"},
        headers=auth_headers,
    )
    assert updated.status_code == 200
    assert updated.json()["date_of_joining"] == "2026-03-15"
    assert client.get(f"/api/v1/employees/{employee_id}", headers=auth_headers).json()["date_of_joining"] == "2026-03-15"
    assert client.get(
        f"/api/v1/attendance/monthly?employee_id={employee_id}&month=1&year=2026",
        headers=auth_headers,
    ).json() == []
    readiness = client.get("/api/v1/attendance/readiness?month=1&year=2026", headers=auth_headers).json()[0]
    assert readiness["eligible"] is False
    assert readiness["recorded_days"] == 0
    assert client.get("/api/v1/attendance/leave-summary?month=1&year=2026", headers=auth_headers).json() == []


def test_joining_date_change_with_affected_slip_is_rejected(client, auth_headers, sample_employee):
    employee_id = client.post("/api/v1/employees/", json=sample_employee, headers=auth_headers).json()["id"]
    client.post(
        "/api/v1/attendance/bulk",
        json={"employee_id": employee_id, "month": 1, "year": 2026, "leave_dates": []},
        headers=auth_headers,
    )
    slip = client.post(
        f"/api/v1/salary-slips/generate/{employee_id}",
        json={"month": 1, "year": 2026},
        headers=auth_headers,
    )
    assert slip.status_code == 201

    update = client.put(
        f"/api/v1/employees/{employee_id}",
        json={"date_of_joining": "2026-02-01"},
        headers=auth_headers,
    )
    assert update.status_code == 409
    assert "salary slips" in update.json()["detail"].lower()
    assert client.get(f"/api/v1/employees/{employee_id}", headers=auth_headers).json()["date_of_joining"] == "2024-01-15"

    deleted = client.delete(f"/api/v1/salary-slips/{slip.json()['id']}", headers=auth_headers)
    assert deleted.status_code == 204
    corrected = client.put(
        f"/api/v1/employees/{employee_id}",
        json={"date_of_joining": "2026-02-01"},
        headers=auth_headers,
    )
    assert corrected.status_code == 200
    assert corrected.json()["date_of_joining"] == "2026-02-01"


def test_edit_joining_date_cannot_be_cleared(client, auth_headers, sample_employee):
    employee_id = client.post("/api/v1/employees/", json=sample_employee, headers=auth_headers).json()["id"]
    response = client.put(
        f"/api/v1/employees/{employee_id}", json={"date_of_joining": None}, headers=auth_headers
    )
    assert response.status_code == 400


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
