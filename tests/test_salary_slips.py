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


def test_generate_bulk_slips(client, auth_headers, employee_with_slips):
    response = client.post("/api/v1/salary-slips/generate", json={"month": 3, "year": 2026}, headers=auth_headers)
    assert response.status_code == 201
    data = response.json()
    assert data["generated"] == 1


def test_generate_duplicate_slips(client, auth_headers, employee_with_slips):
    client.post("/api/v1/salary-slips/generate", json={"month": 3, "year": 2026}, headers=auth_headers)
    response = client.post("/api/v1/salary-slips/generate", json={"month": 3, "year": 2026}, headers=auth_headers)
    assert response.status_code == 201
    assert response.json()["generated"] == 0


def test_list_slips(client, auth_headers, employee_with_slips):
    client.post("/api/v1/salary-slips/generate", json={"month": 3, "year": 2026}, headers=auth_headers)
    response = client.get("/api/v1/salary-slips/", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1


def test_get_slip(client, auth_headers, employee_with_slips):
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
    client.post("/api/v1/salary-slips/generate", json={"month": 3, "year": 2026}, headers=auth_headers)
    list_res = client.get("/api/v1/salary-slips/", headers=auth_headers)
    slip = list_res.json()["items"][0]
    expected_gross = 50000 + 20000 + 3000 + 2500 + 5000
    expected_deductions = 6000 + 200 + 5000 + 0
    assert slip["gross_salary"] == expected_gross
    assert slip["total_deductions"] == expected_deductions
    assert slip["net_pay"] == expected_gross - expected_deductions


def test_download_pdf(client, auth_headers, employee_with_slips):
    client.post("/api/v1/salary-slips/generate", json={"month": 3, "year": 2026}, headers=auth_headers)
    list_res = client.get("/api/v1/salary-slips/", headers=auth_headers)
    slip_id = list_res.json()["items"][0]["id"]
    response = client.get(f"/api/v1/salary-slips/{slip_id}/pdf", headers=auth_headers)
    assert response.status_code == 200


def test_filter_slips_by_month(client, auth_headers, employee_with_slips):
    client.post("/api/v1/salary-slips/generate", json={"month": 1, "year": 2026}, headers=auth_headers)
    client.post("/api/v1/salary-slips/generate", json={"month": 2, "year": 2026}, headers=auth_headers)
    response = client.get("/api/v1/salary-slips/?month=1&year=2026", headers=auth_headers)
    assert response.json()["total"] == 1
