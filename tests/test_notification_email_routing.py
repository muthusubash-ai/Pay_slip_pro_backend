from datetime import timedelta

import pytest
from django.utils import timezone

from app.models.user import User


@pytest.fixture
def employee_with_slips(client, auth_headers):
    emp_data = {
        "employee_code": "NOTIF001",
        "full_name": "Notif Employee",
        "email": "notif.employee@example.com",
        "date_of_joining": "2024-01-15",
        "basic_salary": 50000.00,
    }
    emp_res = client.post("/api/v1/employees/", json=emp_data, headers=auth_headers)
    return emp_res.json()


def save_attendance(client, auth_headers, employee_id, month, year):
    response = client.post(
        "/api/v1/attendance/bulk",
        json={"employee_id": employee_id, "month": month, "year": year, "leave_dates": []},
        headers=auth_headers,
    )
    assert response.status_code == 201


def set_notification_email(address: str) -> None:
    User.objects.filter(email="test@example.com").update(notification_email=address)


def test_adding_employee_emails_hr_notice(client, auth_headers, monkeypatch):
    set_notification_email("hr-inbox@example.com")
    captured = {}
    monkeypatch.setattr(
        "app.services.email_service.send_employee_added_notice_email",
        lambda **kwargs: captured.update(kwargs) or True,
    )
    response = client.post("/api/v1/employees/", json={
        "employee_code": "ADDED001",
        "full_name": "Added Employee",
        "email": "added.employee@example.com",
        "date_of_joining": "2024-01-15",
        "basic_salary": 40000.00,
    }, headers=auth_headers)
    assert response.status_code == 201
    assert captured["to_email"] == "hr-inbox@example.com"
    assert captured["employee_name"] == "Added Employee"
    assert captured["employee_code"] == "ADDED001"


def test_bulk_slip_generation_emails_hr_summary(client, auth_headers, employee_with_slips, monkeypatch):
    set_notification_email("hr-inbox@example.com")
    captured = {}
    monkeypatch.setattr(
        "app.services.email_service.send_slip_generation_summary_email",
        lambda **kwargs: captured.update(kwargs) or True,
    )
    save_attendance(client, auth_headers, employee_with_slips["id"], 3, 2026)
    response = client.post("/api/v1/salary-slips/generate", json={"month": 3, "year": 2026}, headers=auth_headers)
    assert response.status_code == 201
    assert captured["to_email"] == "hr-inbox@example.com"
    assert captured["count"] == 1


def test_bulk_slip_generation_skips_email_when_nothing_generated(client, auth_headers, employee_with_slips, monkeypatch):
    set_notification_email("hr-inbox@example.com")
    calls = []
    monkeypatch.setattr(
        "app.services.email_service.send_slip_generation_summary_email",
        lambda **kwargs: calls.append(kwargs) or True,
    )
    save_attendance(client, auth_headers, employee_with_slips["id"], 3, 2026)
    client.post("/api/v1/salary-slips/generate", json={"month": 3, "year": 2026}, headers=auth_headers)
    calls.clear()
    # Second call for the same month generates 0 new slips - no summary email for an empty run.
    client.post("/api/v1/salary-slips/generate", json={"month": 3, "year": 2026}, headers=auth_headers)
    assert calls == []


def test_single_slip_generation_emails_hr_notice(client, auth_headers, employee_with_slips, monkeypatch):
    set_notification_email("hr-inbox@example.com")
    captured = {}
    monkeypatch.setattr(
        "app.services.email_service.send_slip_generated_email",
        lambda **kwargs: captured.update(kwargs) or True,
    )
    employee_id = employee_with_slips["id"]
    save_attendance(client, auth_headers, employee_id, 9, 2026)
    response = client.post(f"/api/v1/salary-slips/generate/{employee_id}", json={"month": 9, "year": 2026}, headers=auth_headers)
    assert response.status_code == 201
    assert captured["to_email"] == "hr-inbox@example.com"
    assert captured["employee_name"] == "Notif Employee"


def test_emailing_slip_to_employee_also_notifies_hr(client, auth_headers, employee_with_slips, monkeypatch, settings):
    set_notification_email("hr-inbox@example.com")
    settings.SMTP_USER = "sender@example.com"
    settings.SMTP_PASSWORD = "app-password"
    monkeypatch.setattr("app.services.email_service.send_salary_slip_email", lambda *a, **k: True)
    captured = {}
    monkeypatch.setattr(
        "app.services.email_service.send_slip_emailed_notice_email",
        lambda **kwargs: captured.update(kwargs) or True,
    )
    save_attendance(client, auth_headers, employee_with_slips["id"], 3, 2026)
    client.post("/api/v1/salary-slips/generate", json={"month": 3, "year": 2026}, headers=auth_headers)
    list_res = client.get("/api/v1/salary-slips/", headers=auth_headers)
    slip_id = list_res.json()["items"][0]["id"]

    response = client.post(f"/api/v1/salary-slips/{slip_id}/email", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["sent"] is True
    assert captured["to_email"] == "hr-inbox@example.com"
    assert captured["employee_name"] == "Notif Employee"


def test_plan_expiry_dedup_stage_change_and_renewal_reset(monkeypatch):
    from app.services.plan_notification_service import check_and_notify_plan_expiry

    captured = []
    monkeypatch.setattr(
        "app.services.email_service.send_plan_expiry_notice_email",
        lambda **kwargs: captured.append(kwargs) or True,
    )

    user = User.objects.create_user(
        email="expiry_test@example.com", password="x", full_name="Expiry Owner",
        plan="professional", plan_expires_at=timezone.now() + timedelta(days=3),
    )

    assert check_and_notify_plan_expiry(user) is True
    assert len(captured) == 1
    assert captured[0]["stage"] == "7d"

    user.refresh_from_db()
    assert check_and_notify_plan_expiry(user) is False
    assert len(captured) == 1

    user.plan_expires_at = timezone.now() + timedelta(hours=5)
    user.save(update_fields=["plan_expires_at"])
    user.refresh_from_db()
    assert check_and_notify_plan_expiry(user) is True
    assert len(captured) == 2
    assert captured[1]["stage"] == "24h"

    user.plan_expires_at = timezone.now() + timedelta(days=30)
    user.save(update_fields=["plan_expires_at"])
    user.refresh_from_db()
    assert check_and_notify_plan_expiry(user) is False
    assert len(captured) == 2


def test_plan_expiry_skips_starter_and_missing_expiry(monkeypatch):
    from app.services.plan_notification_service import check_and_notify_plan_expiry

    calls = []
    monkeypatch.setattr(
        "app.services.email_service.send_plan_expiry_notice_email",
        lambda **kwargs: calls.append(kwargs) or True,
    )

    starter_user = User.objects.create_user(
        email="starter_test@example.com", password="x", full_name="Starter Owner",
        plan="starter", plan_expires_at=timezone.now() + timedelta(hours=1),
    )
    assert check_and_notify_plan_expiry(starter_user) is False

    no_expiry_user = User.objects.create_user(
        email="no_expiry_test@example.com", password="x", full_name="No Expiry Owner", plan="enterprise",
    )
    assert check_and_notify_plan_expiry(no_expiry_user) is False
    assert calls == []


def test_plan_expiry_email_failure_does_not_break_dashboard_stats(client, auth_headers, monkeypatch):
    User.objects.filter(email="test@example.com").update(plan_expires_at=timezone.now() + timedelta(hours=2))
    monkeypatch.setattr(
        "app.services.email_service.send_plan_expiry_notice_email",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("SMTP down")),
    )
    response = client.get("/api/v1/dashboard/stats", headers=auth_headers)
    assert response.status_code == 200
