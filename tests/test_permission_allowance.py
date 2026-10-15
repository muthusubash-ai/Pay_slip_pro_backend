from datetime import date


def create_employee(client, auth_headers):
    res = client.post("/api/v1/employees/", json={
        "employee_code": "PERM-01",
        "full_name": "Permission Allowance Tester",
        "email": "permallow@example.com",
        "date_of_joining": "2026-01-01",
        "basic_salary": 30000,
    }, headers=auth_headers)
    assert res.status_code == 201
    return res.json()["id"]


def test_company_permission_allowance_of_1_day_per_month(client, auth_headers):
    comp_res = client.put("/api/v1/company/", json={"permission_days_per_month": 1}, headers=auth_headers)
    assert comp_res.status_code == 200
    assert comp_res.json()["permission_days_per_month"] == 1

    employee_id = create_employee(client, auth_headers)
    month, year = 11, 2026

    # 1 permission -> free (0 deduction)
    bulk_res = client.post("/api/v1/attendance/bulk", json={
        "employee_id": employee_id, "month": month, "year": year,
        "leave_dates": [], "permission_dates": [date(year, month, 2).isoformat()],
    }, headers=auth_headers)
    assert bulk_res.status_code == 201

    summary = client.get(f"/api/v1/attendance/leave-summary?month={month}&year={year}", headers=auth_headers).json()
    emp_summary = [s for s in summary if s["employee_id"] == employee_id][0]
    assert emp_summary["permission_days"] == 1
    assert emp_summary["leave_deduction"] == 0.0

    # A 2nd permission in the same month exceeds the 1/month allowance -> deducts 1 full day.
    # (30000 / 30) * 1 = 1000.0
    bulk_res2 = client.post("/api/v1/attendance/bulk", json={
        "employee_id": employee_id, "month": month, "year": year,
        "leave_dates": [],
        "permission_dates": [date(year, month, 2).isoformat(), date(year, month, 3).isoformat()],
    }, headers=auth_headers)
    assert bulk_res2.status_code == 201

    summary2 = client.get(f"/api/v1/attendance/leave-summary?month={month}&year={year}", headers=auth_headers).json()
    emp_summary2 = [s for s in summary2 if s["employee_id"] == employee_id][0]
    assert emp_summary2["permission_days"] == 2
    assert emp_summary2["leave_deduction"] == 1000.0

    slip_res = client.post(
        f"/api/v1/salary-slips/generate/{employee_id}",
        json={"month": month, "year": year},
        headers=auth_headers,
    )
    assert slip_res.status_code == 201
    assert float(slip_res.json()["leave_deduction"]) == 1000.0


def test_company_permission_allowance_of_2_days_per_month(client, auth_headers):
    client.put("/api/v1/company/", json={"permission_days_per_month": 2}, headers=auth_headers)
    employee_id = create_employee(client, auth_headers)
    month, year = 11, 2026

    # 2 permissions -> free (0 deduction)
    bulk_res = client.post("/api/v1/attendance/bulk", json={
        "employee_id": employee_id, "month": month, "year": year,
        "leave_dates": [],
        "permission_dates": [date(year, month, 2).isoformat(), date(year, month, 3).isoformat()],
    }, headers=auth_headers)
    assert bulk_res.status_code == 201

    summary = client.get(f"/api/v1/attendance/leave-summary?month={month}&year={year}", headers=auth_headers).json()
    emp_summary = [s for s in summary if s["employee_id"] == employee_id][0]
    assert emp_summary["permission_days"] == 2
    assert emp_summary["leave_deduction"] == 0.0


def test_permission_allowance_validation_rejects_out_of_range(client, auth_headers):
    bad_res = client.put("/api/v1/company/", json={"permission_days_per_month": -1}, headers=auth_headers)
    assert bad_res.status_code == 400

    bad_res2 = client.put("/api/v1/company/", json={"permission_days_per_month": 32}, headers=auth_headers)
    assert bad_res2.status_code == 400


def test_default_permission_allowance_is_3_when_no_company_row_exists(client, auth_headers):
    """Company settings are created lazily on first PUT - a brand new user has no Company
    row yet. get_permission_allowance() must still fall back to the historical default of 3."""
    from app.models.user import User
    from app.services.attendance_service import get_permission_allowance

    user = User.objects.get(email="test@example.com")
    assert not hasattr(user, "company") or user.company is None
    assert get_permission_allowance(user) == 3


def test_default_permission_allowance_is_3_once_company_row_exists(client, auth_headers):
    """Once a Company row exists (e.g. after saving any other setting) but
    permission_days_per_month was never explicitly set, the model default of 3 applies."""
    client.put("/api/v1/company/", json={"company_name": "Acme Corp"}, headers=auth_headers)
    comp_res = client.get("/api/v1/company/", headers=auth_headers)
    assert comp_res.json()["permission_days_per_month"] == 3
