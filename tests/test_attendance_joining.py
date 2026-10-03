from datetime import date

from app.models.attendance import Attendance
from app.models.employee import Employee
from app.models.user import User


def create_employee(client, auth_headers):
    response = client.post(
        "/api/v1/employees/",
        json={
            "employee_code": "JOIN-SEP",
            "full_name": "September Joiner",
            "email": "september@example.com",
            "date_of_joining": "2026-09-15",
            "basic_salary": 30000,
        },
        headers=auth_headers,
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_attendance_before_joining_is_hidden_and_cannot_be_saved(client, auth_headers):
    employee_id = create_employee(client, auth_headers)
    # Existing data from before this rule must not leak into historical views.
    Attendance.objects.create(
        user=User.objects.get(email="test@example.com"),
        employee=Employee.objects.get(id=employee_id),
        date=date(2026, 8, 20),
        status="present",
    )
    single = client.post(
        "/api/v1/attendance/",
        json={"employee_id": employee_id, "date": "2026-08-20", "status": "present"},
        headers=auth_headers,
    )
    assert single.status_code == 400
    bulk = client.post(
        "/api/v1/attendance/bulk",
        json={"employee_id": employee_id, "month": 8, "year": 2026, "leave_dates": [], "weekoff_dates": []},
        headers=auth_headers,
    )
    assert bulk.status_code == 400
    monthly = client.get(
        f"/api/v1/attendance/monthly?employee_id={employee_id}&month=8&year=2026",
        headers=auth_headers,
    )
    assert monthly.status_code == 200
    assert monthly.json() == []
    readiness = client.get("/api/v1/attendance/readiness?month=8&year=2026", headers=auth_headers)
    assert readiness.json()[0]["eligible"] is False
    assert readiness.json()[0]["complete"] is False
    assert readiness.json()[0]["recorded_days"] == 0
    summary = client.get("/api/v1/attendance/leave-summary?month=8&year=2026", headers=auth_headers)
    assert summary.json() == []


def test_joining_month_only_counts_days_from_joining_date(client, auth_headers):
    employee_id = create_employee(client, auth_headers)
    invalid = client.post(
        "/api/v1/attendance/bulk",
        json={
            "employee_id": employee_id, "month": 9, "year": 2026,
            "leave_dates": ["2026-09-14"], "weekoff_dates": [],
        },
        headers=auth_headers,
    )
    assert invalid.status_code == 400

    saved = client.post(
        "/api/v1/attendance/bulk",
        json={
            "employee_id": employee_id, "month": 9, "year": 2026,
            "leave_dates": ["2026-09-16"], "weekoff_dates": [],
        },
        headers=auth_headers,
    )
    assert saved.status_code == 201
    assert saved.json()["count"] == 16
    monthly = client.get(
        f"/api/v1/attendance/monthly?employee_id={employee_id}&month=9&year=2026",
        headers=auth_headers,
    ).json()
    assert len(monthly) == 16
    assert monthly[0]["date"] == "2026-09-15"
    readiness = client.get("/api/v1/attendance/readiness?month=9&year=2026", headers=auth_headers).json()[0]
    assert readiness["total_days"] == 16
    assert readiness["complete"] is True
    summary = client.get("/api/v1/attendance/leave-summary?month=9&year=2026", headers=auth_headers).json()[0]
    assert summary["total_days"] == 16
    assert summary["present_days"] == 15
    assert summary["leave_days"] == 1
    slip = client.post(
        f"/api/v1/salary-slips/generate/{employee_id}",
        json={"month": 9, "year": 2026},
        headers=auth_headers,
    )
    assert slip.status_code == 201


def test_weekoff_halfday_limit_and_no_deduction(client, auth_headers):
    emp_res = client.post(
        "/api/v1/employees/",
        json={
            "employee_code": "WK-HALF-01",
            "full_name": "Weekoff Half Tester",
            "email": "wkhalf@example.com",
            "date_of_joining": "2026-09-01",
            "basic_salary": 30000,
        },
        headers=auth_headers,
    )
    assert emp_res.status_code == 201
    employee_id = emp_res.json()["id"]

    # 1. Attempting 3 weekoff halfdays must fail with 400 validation error
    fail_res = client.post(
        "/api/v1/attendance/bulk",
        json={
            "employee_id": employee_id,
            "month": 9,
            "year": 2026,
            "leave_dates": [],
            "weekoff_dates": [],
            "weekoff_halfday_dates": ["2026-09-05", "2026-09-12", "2026-09-19"],
        },
        headers=auth_headers,
    )
    assert fail_res.status_code == 400
    assert "maximum 2 weekoff halfdays" in fail_res.text.lower()

    # 2. Saving 2 weekoff halfdays must succeed
    save_res = client.post(
        "/api/v1/attendance/bulk",
        json={
            "employee_id": employee_id,
            "month": 9,
            "year": 2026,
            "leave_dates": [],
            "weekoff_dates": [],
            "weekoff_halfday_dates": ["2026-09-05", "2026-09-12"],
        },
        headers=auth_headers,
    )
    assert save_res.status_code == 201
    assert save_res.json()["count"] == 30

    # 3. Check leave summary: weekoff_halfday_days is 2, leave_deduction is 0.0
    summary_res = client.get("/api/v1/attendance/leave-summary?month=9&year=2026", headers=auth_headers)
    assert summary_res.status_code == 200
    emp_summary = [s for s in summary_res.json() if s["employee_id"] == employee_id][0]
    assert emp_summary["weekoff_halfday_days"] == 2
    assert emp_summary["leave_days"] == 0
    assert emp_summary["leave_deduction"] == 0.0
    assert emp_summary["present_days"] == 28

    # 4. Generate slip: leave_deduction must be 0.0
    slip_res = client.post(
        f"/api/v1/salary-slips/generate/{employee_id}",
        json={"month": 9, "year": 2026},
        headers=auth_headers,
    )
    assert slip_res.status_code == 201
    assert float(slip_res.json()["leave_deduction"]) == 0.0

