import calendar
from datetime import date


def create_employee(client, auth_headers):
    res = client.post("/api/v1/employees/", json={
        "employee_code": "WKOFF-01",
        "full_name": "Weekly Off Tester",
        "email": "weeklyoff@example.com",
        "date_of_joining": "2026-01-01",
        "basic_salary": 30000,
    }, headers=auth_headers)
    assert res.status_code == 201
    return res.json()["id"]


def test_company_weekly_off_day_is_always_free_and_excluded_from_monthly_quota(client, auth_headers):
    # Configure Sunday (weekday 6, per Company.weekly_off_days convention) as the
    # company's standing weekly off day.
    comp_res = client.put("/api/v1/company/", json={"weekly_off_days": [6]}, headers=auth_headers)
    assert comp_res.status_code == 200
    assert comp_res.json()["weekly_off_days"] == [6]

    employee_id = create_employee(client, auth_headers)

    month, year = 11, 2026
    total_days = calendar.monthrange(year, month)[1]
    sundays = [date(year, month, d) for d in range(1, total_days + 1) if date(year, month, d).weekday() == 6]
    non_sundays = [date(year, month, d) for d in range(1, total_days + 1) if date(year, month, d).weekday() != 6]
    assert len(sundays) >= 2

    # Mark a Sunday AND a weekday as leave_dates. The Sunday must be forced to
    # company_week_off (never consuming the 1 free Weekoff/month allowance); the
    # weekday leave should become that free Weekoff instead.
    leave_dates = [sundays[0].isoformat(), non_sundays[0].isoformat()]
    bulk_res = client.post("/api/v1/attendance/bulk", json={
        "employee_id": employee_id, "month": month, "year": year,
        "leave_dates": leave_dates,
    }, headers=auth_headers)
    assert bulk_res.status_code == 201

    monthly = client.get(
        f"/api/v1/attendance/monthly?employee_id={employee_id}&month={month}&year={year}",
        headers=auth_headers,
    ).json()
    by_date = {row["date"]: row["status"] for row in monthly}
    assert by_date[non_sundays[0].isoformat()] == "weekoff"
    # Every Sunday in the month is company_week_off, even the ones never explicitly marked.
    for s in sundays:
        assert by_date[s.isoformat()] == "company_week_off"

    summary = client.get(f"/api/v1/attendance/leave-summary?month={month}&year={year}", headers=auth_headers).json()
    emp_summary = [s for s in summary if s["employee_id"] == employee_id][0]
    assert emp_summary["company_week_off_days"] == len(sundays)
    assert emp_summary["weekoff_days"] == 1
    assert emp_summary["leave_days"] == 0
    assert emp_summary["leave_deduction"] == 0.0

    slip_res = client.post(
        f"/api/v1/salary-slips/generate/{employee_id}",
        json={"month": month, "year": year},
        headers=auth_headers,
    )
    assert slip_res.status_code == 201
    assert float(slip_res.json()["leave_deduction"]) == 0.0


def test_second_full_leave_in_same_month_still_deducts_despite_weekly_off(client, auth_headers):
    client.put("/api/v1/company/", json={"weekly_off_days": [6]}, headers=auth_headers)
    employee_id = create_employee(client, auth_headers)

    month, year = 11, 2026
    total_days = calendar.monthrange(year, month)[1]
    non_sundays = [date(year, month, d) for d in range(1, total_days + 1) if date(year, month, d).weekday() != 6]

    # Two full-day leaves on working (non-Sunday) days: 1st is free Weekoff, 2nd deducts 1 day.
    # (30000 / 30) * 1 = 1000.0
    bulk_res = client.post("/api/v1/attendance/bulk", json={
        "employee_id": employee_id, "month": month, "year": year,
        "leave_dates": [non_sundays[0].isoformat(), non_sundays[1].isoformat()],
    }, headers=auth_headers)
    assert bulk_res.status_code == 201

    summary = client.get(f"/api/v1/attendance/leave-summary?month={month}&year={year}", headers=auth_headers).json()
    emp_summary = [s for s in summary if s["employee_id"] == employee_id][0]
    assert emp_summary["weekoff_days"] == 1
    assert emp_summary["leave_days"] == 1
    assert emp_summary["leave_deduction"] == 1000.0


def test_no_weekly_off_configured_is_backward_compatible(client, auth_headers):
    """A company that never configures weekly_off_days behaves exactly as before."""
    employee_id = create_employee(client, auth_headers)
    month, year = 9, 2026

    bulk_res = client.post("/api/v1/attendance/bulk", json={
        "employee_id": employee_id, "month": month, "year": year, "leave_dates": [],
    }, headers=auth_headers)
    assert bulk_res.status_code == 201

    summary = client.get(f"/api/v1/attendance/leave-summary?month={month}&year={year}", headers=auth_headers).json()
    emp_summary = [s for s in summary if s["employee_id"] == employee_id][0]
    assert emp_summary["company_week_off_days"] == 0
