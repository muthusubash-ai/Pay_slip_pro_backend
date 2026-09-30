import pytest


@pytest.fixture
def employee_with_slips(client, auth_headers):
    emp_data = {
        "employee_code": "EMP001",
        "full_name": "John Doe",
        "email": "john@company.com",
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
    emp_res = client.post("/api/v1/employees/", json=emp_data, headers=auth_headers)
    return emp_res.json()


def save_attendance(client, auth_headers, employee_id, month, year):
    response = client.post(
        "/api/v1/attendance/bulk",
        json={"employee_id": employee_id, "month": month, "year": year, "leave_dates": [], "weekoff_dates": []},
        headers=auth_headers,
    )
    assert response.status_code == 201


def test_generate_bulk_slips(client, auth_headers, employee_with_slips):
    save_attendance(client, auth_headers, employee_with_slips["id"], 3, 2026)
    response = client.post("/api/v1/salary-slips/generate", json={"month": 3, "year": 2026}, headers=auth_headers)
    assert response.status_code == 201
    data = response.json()
    assert data["generated"] == 1


def test_generate_duplicate_slips(client, auth_headers, employee_with_slips):
    save_attendance(client, auth_headers, employee_with_slips["id"], 3, 2026)
    client.post("/api/v1/salary-slips/generate", json={"month": 3, "year": 2026}, headers=auth_headers)
    response = client.post("/api/v1/salary-slips/generate", json={"month": 3, "year": 2026}, headers=auth_headers)
    assert response.status_code == 201
    assert response.json()["generated"] == 0


def test_list_slips(client, auth_headers, employee_with_slips):
    save_attendance(client, auth_headers, employee_with_slips["id"], 3, 2026)
    client.post("/api/v1/salary-slips/generate", json={"month": 3, "year": 2026}, headers=auth_headers)
    response = client.get("/api/v1/salary-slips/", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1


def test_get_slip(client, auth_headers, employee_with_slips):
    save_attendance(client, auth_headers, employee_with_slips["id"], 3, 2026)
    client.post("/api/v1/salary-slips/generate", json={"month": 3, "year": 2026}, headers=auth_headers)
    list_res = client.get("/api/v1/salary-slips/", headers=auth_headers)
    slip_id = list_res.json()["items"][0]["id"]
    response = client.get(f"/api/v1/salary-slips/{slip_id}", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["gross_salary"] == 80500.00
    assert data["total_deductions"] == 11200.00
    assert data["net_pay"] == 69300.00


def test_salary_calculation(client, auth_headers, employee_with_slips):
    save_attendance(client, auth_headers, employee_with_slips["id"], 3, 2026)
    client.post("/api/v1/salary-slips/generate", json={"month": 3, "year": 2026}, headers=auth_headers)
    list_res = client.get("/api/v1/salary-slips/", headers=auth_headers)
    slip = list_res.json()["items"][0]
    expected_gross = 50000 + 20000 + 3000 + 2500 + 5000
    expected_deductions = 6000 + 200 + 5000 + 0
    assert slip["gross_salary"] == expected_gross
    assert slip["total_deductions"] == expected_deductions
    assert slip["net_pay"] == expected_gross - expected_deductions


def test_download_pdf(client, auth_headers, employee_with_slips):
    save_attendance(client, auth_headers, employee_with_slips["id"], 3, 2026)
    client.post("/api/v1/salary-slips/generate", json={"month": 3, "year": 2026}, headers=auth_headers)
    list_res = client.get("/api/v1/salary-slips/", headers=auth_headers)
    slip_id = list_res.json()["items"][0]["id"]
    response = client.get(f"/api/v1/salary-slips/{slip_id}/pdf", headers=auth_headers)
    assert response.status_code == 200


def test_filter_slips_by_month(client, auth_headers, employee_with_slips):
    save_attendance(client, auth_headers, employee_with_slips["id"], 1, 2026)
    save_attendance(client, auth_headers, employee_with_slips["id"], 2, 2026)
    client.post("/api/v1/salary-slips/generate", json={"month": 1, "year": 2026}, headers=auth_headers)
    client.post("/api/v1/salary-slips/generate", json={"month": 2, "year": 2026}, headers=auth_headers)
    response = client.get("/api/v1/salary-slips/?month=1&year=2026", headers=auth_headers)
    assert response.json()["total"] == 1


def test_single_slip_requires_complete_attendance_for_same_month(client, auth_headers, employee_with_slips):
    employee_id = employee_with_slips["id"]
    url = f"/api/v1/salary-slips/generate/{employee_id}"
    missing = client.post(url, json={"month": 9, "year": 2026}, headers=auth_headers)
    assert missing.status_code == 400
    assert "attendance" in missing.json()["detail"].lower()

    client.post(
        "/api/v1/attendance/",
        json={"employee_id": employee_id, "date": "2026-09-01", "status": "present"},
        headers=auth_headers,
    )
    partial = client.post(url, json={"month": 9, "year": 2026}, headers=auth_headers)
    assert partial.status_code == 400

    save_attendance(client, auth_headers, employee_id, 8, 2026)
    wrong_month = client.post(url, json={"month": 9, "year": 2026}, headers=auth_headers)
    assert wrong_month.status_code == 400

    save_attendance(client, auth_headers, employee_id, 9, 2026)
    ready = client.post(url, json={"month": 9, "year": 2026}, headers=auth_headers)
    assert ready.status_code == 201


def test_bulk_skips_employee_without_attendance(client, auth_headers, employee_with_slips):
    response = client.post("/api/v1/salary-slips/generate", json={"month": 9, "year": 2026}, headers=auth_headers)
    assert response.status_code == 201
    assert response.json()["generated"] == 0
    assert response.json()["attendance_pending_employee_ids"] == [employee_with_slips["id"]]


def test_bulk_generates_only_for_employees_with_saved_attendance(client, auth_headers, employee_with_slips):
    second_payload = {
        "employee_code": "EMP002",
        "full_name": "Jane Doe",
        "email": "jane@company.com",
        "date_of_joining": "2024-01-15",
        "basic_salary": 30000,
    }
    second = client.post("/api/v1/employees/", json=second_payload, headers=auth_headers).json()
    save_attendance(client, auth_headers, employee_with_slips["id"], 9, 2026)

    response = client.post("/api/v1/salary-slips/generate", json={"month": 9, "year": 2026}, headers=auth_headers)
    assert response.status_code == 201
    assert response.json()["generated"] == 1
    assert response.json()["attendance_pending_employee_ids"] == [second["id"]]

    save_attendance(client, auth_headers, second["id"], 9, 2026)
    retry = client.post("/api/v1/salary-slips/generate", json={"month": 9, "year": 2026}, headers=auth_headers)
    assert retry.json()["generated"] == 1
    assert retry.json()["attendance_pending_employee_ids"] == []
