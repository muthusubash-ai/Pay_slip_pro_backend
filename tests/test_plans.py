import pytest

from app.models.user import User


@pytest.fixture
def sample_employee_payload():
    return {
        "employee_code": "PLAN-EMP",
        "full_name": "Plan Employee",
        "email": "plan.employee@example.com",
        "date_of_joining": "2026-01-01",
        "basic_salary": 30000,
    }


def set_plan(plan: str) -> None:
    User.objects.filter(email="test@example.com").update(plan=plan)


def test_me_returns_current_plan(client, auth_headers):
    response = client.get("/api/v1/auth/me", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["plan"] == "enterprise"


def test_starter_gets_basic_dashboard_but_not_professional_features(client, auth_headers):
    set_plan("starter")

    assert client.get("/api/v1/dashboard/stats", headers=auth_headers).status_code == 200
    assert client.get("/api/v1/dashboard/payroll-summary", headers=auth_headers).status_code == 403
    assert client.get("/api/v1/company/", headers=auth_headers).status_code == 403
    assert client.get(
        "/api/v1/attendance/leave-summary?month=1&year=2026",
        headers=auth_headers,
    ).status_code == 403


def test_starter_can_save_monthly_attendance_and_then_generate_slip(client, auth_headers, sample_employee_payload):
    set_plan("starter")
    employee = client.post("/api/v1/employees/", json=sample_employee_payload, headers=auth_headers).json()
    employee_id = employee["id"]
    assert client.get(
        f"/api/v1/attendance/monthly?employee_id={employee_id}&month=9&year=2026",
        headers=auth_headers,
    ).status_code == 200
    assert client.post(
        f"/api/v1/salary-slips/generate/{employee_id}",
        json={"month": 9, "year": 2026}, headers=auth_headers,
    ).status_code == 400
    saved = client.post(
        "/api/v1/attendance/bulk",
        json={"employee_id": employee_id, "month": 9, "year": 2026, "leave_dates": [], "weekoff_dates": []},
        headers=auth_headers,
    )
    assert saved.status_code == 201
    readiness = client.get("/api/v1/attendance/readiness?month=9&year=2026", headers=auth_headers)
    assert readiness.status_code == 200
    assert readiness.json()[0]["complete"] is True
    assert client.post(
        f"/api/v1/salary-slips/generate/{employee_id}",
        json={"month": 9, "year": 2026}, headers=auth_headers,
    ).status_code == 201


def test_starter_cannot_use_professional_bulk_generation(client, auth_headers):
    set_plan("starter")
    response = client.post(
        "/api/v1/salary-slips/generate",
        json={"month": 9, "year": 2026},
        headers=auth_headers,
    )
    assert response.status_code == 403
    assert "professional" in response.json()["detail"].lower()


def test_starter_employee_limit(client, auth_headers, sample_employee_payload):
    set_plan("starter")

    for index in range(3):
        payload = {
            **sample_employee_payload,
            "employee_code": f"PLAN-{index}",
            "email": f"plan{index}@example.com",
        }
        assert client.post("/api/v1/employees/", json=payload, headers=auth_headers).status_code == 201

    response = client.post(
        "/api/v1/employees/",
        json={
            **sample_employee_payload,
            "employee_code": "PLAN-4",
            "email": "plan4@example.com",
        },
        headers=auth_headers,
    )
    assert response.status_code == 403
    assert "up to 3 active employees" in response.json()["detail"]


def test_professional_limit_and_feature_access(client, auth_headers):
    set_plan("professional")

    assert client.get("/api/v1/dashboard/stats", headers=auth_headers).status_code == 200
    assert client.get("/api/v1/company/", headers=auth_headers).status_code == 200
    assert client.get("/api/v1/dashboard/department-breakdown", headers=auth_headers).status_code == 403


def test_enterprise_can_open_enterprise_insights(client, auth_headers):
    set_plan("enterprise")

    assert client.get("/api/v1/dashboard/department-breakdown", headers=auth_headers).status_code == 200
    assert client.get(
        "/api/v1/attendance/leave-summary?month=1&year=2026",
        headers=auth_headers,
    ).status_code == 200


def test_plan_expiry_sets_is_plan_expired_and_restricts_access(client, auth_headers):
    from datetime import timedelta
    from django.utils import timezone

    user = User.objects.get(email="test@example.com")
    user.plan = "professional"
    user.plan_expires_at = timezone.now() - timedelta(days=2)
    user.save(update_fields=["plan", "plan_expires_at", "updated_at"])

    res = client.get("/api/v1/auth/me", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["plan"] == "professional"
    assert data["is_plan_expired"] is True
    assert data["plan_days_left"] == 0

    # Professional features are restricted
    assert client.get("/api/v1/company/", headers=auth_headers).status_code == 403


def test_plan_active_returns_not_expired(client, auth_headers):
    from datetime import timedelta
    from django.utils import timezone

    user = User.objects.get(email="test@example.com")
    user.plan = "professional"
    user.plan_expires_at = timezone.now() + timedelta(days=15)
    user.save(update_fields=["plan", "plan_expires_at", "updated_at"])

    res = client.get("/api/v1/auth/me", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["plan"] == "professional"
    assert data["is_plan_expired"] is False
    assert data["plan_days_left"] >= 14

    assert client.get("/api/v1/company/", headers=auth_headers).status_code == 200
