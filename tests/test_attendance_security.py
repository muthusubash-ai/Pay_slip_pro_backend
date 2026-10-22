from datetime import date, datetime, time, timedelta
from io import BytesIO

import pytest
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image
from rest_framework.response import Response
from rest_framework.test import APIClient

from app.models.company import Company
from app.models.employee import Employee as PayrollEmployee
from app.models.user import User
from attendance.models import (
    ActivationInvite,
    Attendance,
    Employee,
    EmployeeSession,
    LeaveRequest,
)
from attendance.security import COOKIE, encode_photo, issue_invite, set_session

PASSWORD = 'SecureAttendance123!'
PREFIX = '/api/attendance/'


@pytest.fixture
def accounts():
    result = []
    for index in range(2):
        owner = User.objects.create_user(email=f'owner{index}@example.com', password=PASSWORD, full_name='Company Owner', plan='enterprise')
        Company.objects.create(user=owner, company_name=f'Company {index}', office_lat=8.78, office_lng=78.11, allowed_radius_meters=70)
        payroll = PayrollEmployee.objects.create(user=owner, employee_code='EMP001', full_name=f'Employee {index}', email=f'employee{index}@example.com', date_of_joining=date(2020, 1, 1))
        employee = Employee.objects.create(emp_id=payroll.employee_code, full_name=payroll.full_name, email=payroll.email, payroll_employee=payroll, face_encoding=[0.1] * 128)
        employee.set_password(PASSWORD)
        employee.save()
        result.append((owner, payroll, employee))
    return result


def session_client(employee, csrf=False):
    client = APIClient(enforce_csrf_checks=csrf)
    response = set_session(Response({}), employee)
    client.cookies[COOKIE] = response.cookies[COOKIE].value
    return client


def csrf_post(client, path, data, **extra):
    token = client.get('/api/v1/auth/csrf').data['csrf_token']
    client.cookies['csrftoken'] = token
    return client.post(path, data, HTTP_X_CSRFTOKEN=token, **extra)


@pytest.mark.parametrize('route,method', [
    ('history/?emp_id=EMP001', 'get'), ('monthly-summary/?emp_id=EMP001', 'get'),
    ('my-leaves/?emp_id=EMP001', 'get'), ('update-profile/', 'post'),
    ('mark-attendance/', 'post'), ('leave-request/', 'post'),
    ('leave-action/', 'get'), ('leave-action/', 'post'), ('sync-to-payslippro/', 'post'),
])
def test_anonymous_sensitive_routes_are_denied(accounts, route, method):
    response = getattr(APIClient(), method)(PREFIX + route)
    assert response.status_code in (401, 403)


def test_no_public_directory_or_descriptors(accounts):
    client = APIClient()
    assert client.get(PREFIX + 'registered-descriptors/').status_code == 410
    assert client.get(PREFIX + 'lookup-employee/?all=1').status_code == 403
    assert client.get(PREFIX + 'config/?emp_id=EMP001').status_code == 403


def test_bypass_partial_identifier_and_inactive_login_denied(accounts):
    client = APIClient()
    employee = accounts[0][2]
    for body in [
        {'identifier': employee.email, 'password': 'google_oauth_bypass'},
        {'identifier': 'employee0', 'password': PASSWORD},
        {'identifier': 'EMP001', 'password': PASSWORD},  # ambiguous across companies
    ]:
        assert csrf_post(client, PREFIX + 'login/', body).status_code == 401
    employee.is_active = False
    employee.save()
    assert csrf_post(client, PREFIX + 'login/', {'identifier': employee.email, 'password': PASSWORD}).status_code == 401
    employee.refresh_from_db()
    assert not employee.is_active


def test_passwordless_account_cannot_claim_password(accounts):
    employee = accounts[0][2]
    employee.password = None
    employee.save()
    assert not employee.check_password(PASSWORD)
    employee.refresh_from_db()
    assert employee.password is None


def test_login_cookie_and_no_biometric_or_tokens_in_response(accounts, settings):
    settings.DEBUG = False
    settings.SECURE_SSL_REDIRECT = False
    employee = accounts[0][2]
    response = APIClient().post(PREFIX + 'login/', {'identifier': employee.email, 'password': PASSWORD})
    assert response.status_code == 200
    assert response.cookies[COOKIE]['httponly']
    assert response.cookies[COOKIE]['secure']
    assert not {'access_token', 'refresh_token', 'face_descriptor'} & response.data.keys()


def test_history_is_scoped_even_with_duplicate_employee_codes(accounts):
    other = accounts[1][2]
    Attendance.objects.create(employee=other, punch_latitude=8.78, punch_longitude=78.11, distance_meters=0)
    client = session_client(accounts[0][2])
    response = client.get(PREFIX + 'history/?emp_id=EMP001')
    assert response.status_code == 200
    assert response.data == []
    assert client.get(PREFIX + 'history/?emp_id=OTHER').status_code == 403
    assert client.post(PREFIX + 'leave-action/', {'request_id': 1, 'action': 'APPROVED'}).status_code in (401, 403)


def test_employee_password_change_requires_current_and_revokes_sessions(accounts):
    employee = accounts[0][2]
    client = session_client(employee)
    old_client = session_client(employee)
    assert client.post(PREFIX + 'update-profile/', {'new_password': 'DifferentSecure123!'}).status_code == 403
    response = client.post(PREFIX + 'update-profile/', {'current_password': PASSWORD, 'new_password': 'DifferentSecure123!', 'email': 'attacker@example.com', 'joining_date': '2000-01-01'})
    assert response.status_code == 200
    assert old_client.get(PREFIX + 'me/').status_code == 401
    employee.refresh_from_db()
    assert employee.email == accounts[0][1].email
    assert employee.check_password('DifferentSecure123!')


def test_csrf_required_on_login_and_cookie_mutations(accounts):
    employee = accounts[0][2]
    client = session_client(employee, csrf=True)
    assert client.post(PREFIX + 'update-profile/', {'phone_number': '9876543210'}).status_code == 403
    assert APIClient(enforce_csrf_checks=True).post(PREFIX + 'login/', {'identifier': employee.email, 'password': PASSWORD}).status_code == 403
    result = client.get('/api/v1/auth/csrf')
    token = result.data['csrf_token']
    assert client.post(PREFIX + 'update-profile/', {'phone_number': '9876543210'}, HTTP_X_CSRFTOKEN=token).status_code == 200


def test_owner_leave_scope_and_get_has_no_side_effect(accounts):
    owner, _, employee = accounts[0]
    leave = LeaveRequest.objects.create(employee=employee, request_type='CASUAL', start_date=date.today(), end_date=date.today(), reason='<script>bad</script>')
    client = APIClient()
    client.force_authenticate(user=accounts[1][0])
    assert client.get(PREFIX + 'leave-action/').data['leave_requests'] == []
    assert client.post(PREFIX + 'leave-action/', {'request_id': leave.pk, 'action': 'APPROVED'}).status_code == 403
    client.force_authenticate(user=owner)
    assert client.get(PREFIX + f'leave-action/?request_id={leave.pk}&action=APPROVED').status_code == 200
    leave.refresh_from_db()
    assert leave.status == 'PENDING'
    assert client.post(PREFIX + 'leave-action/', {'request_id': leave.pk, 'action': 'APPROVED'}).status_code == 200


def test_invite_required_single_use_and_server_owned_identity(accounts, monkeypatch):
    _, payroll, employee = accounts[0]
    # Simulate an account that hasn't completed registration yet (no password on
    # file) - a fresh invite must let it register once, but not again afterwards.
    employee.password = None
    employee.save(update_fields=['password'])
    client = APIClient()
    assert client.post(PREFIX + 'register/', {'password': PASSWORD}).status_code == 403
    token = issue_invite(payroll)
    monkeypatch.setattr('attendance.secure_views.encode_photo', lambda _: [0.2] * 128)
    body = {'password': PASSWORD, 'emp_id': 'WRONG', 'email': 'attacker@example.com', 'joining_date': '1900-01-01'}
    response = client.post(PREFIX + 'register/', body, HTTP_X_ATTENDANCE_INVITE=token)
    assert response.status_code == 201
    assert response.data['emp_id'] == payroll.employee_code
    assert response.data['email'] == payroll.email
    assert client.post(PREFIX + 'register/', body, HTTP_X_ATTENDANCE_INVITE=token).status_code == 403


def test_expired_and_superseded_invites_denied(accounts):
    payroll = accounts[0][1]
    old = issue_invite(payroll)
    current = issue_invite(payroll)
    assert APIClient().get(PREFIX + 'lookup-employee/', HTTP_X_ATTENDANCE_INVITE=old).status_code == 403
    ActivationInvite.objects.filter(used=False).update(expires_at=timezone.now() - timedelta(seconds=1))
    assert APIClient().get(PREFIX + 'lookup-employee/', HTTP_X_ATTENDANCE_INVITE=current).status_code == 403


def test_logout_and_deactivation_revoke_access(accounts):
    employee = accounts[0][2]
    client = session_client(employee)
    replay = APIClient()
    replay.cookies = client.cookies.copy()
    assert client.post(PREFIX + 'logout/').status_code == 200
    assert replay.get(PREFIX + 'me/').status_code == 401
    client = session_client(employee)
    payroll = accounts[0][1]
    payroll.is_active = False
    payroll.save()
    assert client.get(PREFIX + 'me/').status_code == 401


def test_google_requires_verified_credential_and_browser_nonce(accounts, monkeypatch, settings):
    settings.GOOGLE_CLIENT_ID = 'test-client'
    client = APIClient()
    nonce = client.get(PREFIX + 'google/nonce/').data['nonce']
    claims = {'sub': 'google-sub', 'email': accounts[0][2].email, 'email_verified': True, 'nonce': nonce}
    monkeypatch.setattr('attendance.secure_views.verify_google_credential', lambda _: claims)
    assert csrf_post(client, PREFIX + 'google/login/', {'email': accounts[0][2].email}).status_code == 401
    claims['email_verified'] = False
    assert csrf_post(client, PREFIX + 'google/login/', {'credential': 'test-signed-token'}).status_code == 401
    claims['email_verified'] = True
    assert csrf_post(client, PREFIX + 'google/login/', {'credential': 'test-signed-token'}).status_code == 200
    client.cookies['attendance_google_nonce'] = nonce
    assert csrf_post(client, PREFIX + 'google/login/', {'credential': 'test-signed-token'}).status_code == 401


def test_actual_google_verifier_rejects_unsigned_token(settings):
    from attendance.secure_views import verify_google_credential
    settings.GOOGLE_CLIENT_ID = 'test-client'
    # Invalid input is rejected even if a forged browser claims a verified email.
    from unittest.mock import patch
    with patch('google.auth.transport.requests.Request') as transport:
        transport.return_value.return_value.status = 200
        transport.return_value.return_value.data = b'{}'
        with pytest.raises(Exception):
            verify_google_credential('not-a-signed-token')


def test_login_throttled(accounts):
    client = APIClient()
    body = {'identifier': accounts[0][2].email, 'password': 'wrong'}
    responses = [csrf_post(client, PREFIX + 'login/', body).status_code for _ in range(6)]
    assert responses == [401] * 5 + [429]


def test_browser_face_vector_cannot_replace_photo(accounts):
    client = session_client(accounts[0][2])
    response = client.post(PREFIX + 'mark-attendance/', {'latitude': 8.78, 'longitude': 78.11, 'face_descriptor': [0.1] * 128}, format='json')
    assert response.status_code == 400
    assert not Attendance.objects.exists()


@pytest.mark.parametrize('coords', [{'latitude': 'nan', 'longitude': 78}, {'latitude': 200, 'longitude': 78}])
def test_invalid_geolocation_denied(accounts, coords):
    assert session_client(accounts[0][2]).post(PREFIX + 'mark-attendance/', coords).status_code == 400


def test_upload_validation_rejects_invalid_and_oversized_files(settings):
    from rest_framework.exceptions import ValidationError
    with pytest.raises(ValidationError):
        encode_photo(SimpleUploadedFile('photo.jpg', b'<html>invalid</html>', content_type='image/jpeg'))
    settings.MAX_UPLOAD_SIZE = 10
    with pytest.raises(ValidationError):
        encode_photo(SimpleUploadedFile('photo.jpg', b'x' * 11))


def test_biometric_dependency_failure_fails_closed(monkeypatch):
    import sys

    from attendance.security import BiometricUnavailable
    image = BytesIO()
    Image.new('RGB', (20, 20)).save(image, format='PNG')
    monkeypatch.setitem(sys.modules, 'face_recognition', None)
    with pytest.raises(BiometricUnavailable):
        encode_photo(SimpleUploadedFile('photo.png', image.getvalue(), content_type='image/png'))


def test_employee_invitation_email_escapes_untrusted_html(monkeypatch):
    from app.services import email_service
    captured = {}
    monkeypatch.setattr(email_service, '_send_email', lambda to, subject, body: captured.update(body=body) or True)
    assert email_service.send_employee_registration_invitation_email(
        'employee@example.com', '<img src=x onerror=alert(1)>', 'EMP001',
        'https://example.com/attendance', '<b>Untrusted Company</b>', 'safe-token',
    )
    assert '<img src=x onerror=alert(1)>' not in captured['body']
    assert '&lt;img src=x onerror=alert(1)&gt;' in captured['body']
    assert '<b>Untrusted Company</b>' not in captured['body']


def test_attendance_forgot_and_reset_password_flow(accounts, monkeypatch):
    client = APIClient()
    owner, payroll, employee = accounts[0]

    captured_code = {}
    from app.services import email_service
    monkeypatch.setattr(
        email_service,
        'send_password_reset_email',
        lambda email, code: captured_code.update(email=email, code=code) or True
    )

    # 1. Ambiguous Employee ID across two companies returns 400 with prompt to use email
    res_ambiguous = csrf_post(client, PREFIX + 'forgot-password/', {'identifier': payroll.employee_code})
    assert res_ambiguous.status_code == 400
    assert 'email' in res_ambiguous.data['detail'].lower()

    # 2. Forgot password by registered email succeeds
    res = csrf_post(client, PREFIX + 'forgot-password/', {'identifier': employee.email})
    assert res.status_code == 200
    assert res.data['sent'] is True
    assert captured_code['email'] == employee.email
    code = captured_code['code']

    # 3. Reset password with wrong code fails
    res_fail = csrf_post(client, PREFIX + 'reset-password/', {
        'identifier': employee.email,
        'code': '000000',
        'new_password': 'NewPassword123!',
    })
    assert res_fail.status_code == 400

    # 4. Reset password with correct code succeeds
    new_pass = 'BrandNewPassword123!'
    res_ok = csrf_post(client, PREFIX + 'reset-password/', {
        'identifier': employee.email,
        'code': code,
        'new_password': new_pass,
    })
    assert res_ok.status_code == 200
    assert res_ok.data['success'] is True

    # 5. Old password cannot sign in, new password can
    employee.refresh_from_db()
    assert employee.check_password(new_pass) is True
    assert employee.check_password(PASSWORD) is False


def test_leave_approval_updates_attendance_hierarchy_and_rejection_no_effect(accounts):
    from app.models.attendance import Attendance as PayrollAttendance, AttendanceStatus
    owner, payroll, employee = accounts[0]
    # Existing attendance punch for today
    Attendance.objects.create(employee=employee, punch_latitude=8.78, punch_longitude=78.11, distance_meters=0)
    client = APIClient()
    client.force_authenticate(user=owner)

    # 1. Rejected request has NO effect on attendance
    rej_date = date(2026, 11, 2)
    rej_leave = LeaveRequest.objects.create(
        employee=employee, request_type='CASUAL', start_date=rej_date, end_date=rej_date, reason='Personal'
    )
    res_rej = client.post(PREFIX + 'leave-action/', {'request_id': rej_leave.pk, 'action': 'REJECTED'})
    assert res_rej.status_code == 200
    rej_leave.refresh_from_db()
    assert rej_leave.status == 'REJECTED'
    assert not PayrollAttendance.objects.filter(employee=payroll, date=rej_date).exists()

    # 2. First full-day leave -> mapped to weekoff, subsequent day -> mapped to leave
    start_d = date(2026, 11, 5)
    end_d = date(2026, 11, 6)
    full_leave = LeaveRequest.objects.create(
        employee=employee, request_type='CASUAL', start_date=start_d, end_date=end_d, reason='Vacation'
    )
    res_app1 = client.post(PREFIX + 'leave-action/', {'request_id': full_leave.pk, 'action': 'APPROVED'})
    assert res_app1.status_code == 200
    full_leave.refresh_from_db()
    assert full_leave.status == 'APPROVED'

    day1 = PayrollAttendance.objects.get(employee=payroll, date=start_d)
    day2 = PayrollAttendance.objects.get(employee=payroll, date=end_d)
    assert day1.status == AttendanceStatus.weekoff
    assert day2.status == AttendanceStatus.leave

    # 3. The full-day Weekoff above already consumed the entire shared 2-unit pool
    # (1 full day = 2 units), so this half-day leave is NOT free - it deducts 0.5 day.
    half_d1 = date(2026, 11, 10)
    hd_leave1 = LeaveRequest.objects.create(
        employee=employee, request_type='HALF_DAY', start_date=half_d1, end_date=half_d1, reason='Doctor'
    )
    res_hd1 = client.post(PREFIX + 'leave-action/', {'request_id': hd_leave1.pk, 'action': 'APPROVED'})
    assert res_hd1.status_code == 200
    rec_hd1 = PayrollAttendance.objects.get(employee=payroll, date=half_d1)
    assert rec_hd1.status == AttendanceStatus.half_day

    # 4. Any further half-day leave that month also deducts - the pool stays exhausted.
    half_d2 = date(2026, 11, 12)
    hd_leave2 = LeaveRequest.objects.create(
        employee=employee, request_type='HALF_DAY', start_date=half_d2, end_date=half_d2, reason='Doctor appointment 2'
    )
    res_hd2 = client.post(PREFIX + 'leave-action/', {'request_id': hd_leave2.pk, 'action': 'APPROVED'})
    assert res_hd2.status_code == 200
    rec_hd2 = PayrollAttendance.objects.get(employee=payroll, date=half_d2)
    assert rec_hd2.status == AttendanceStatus.half_day

    # 5. Permission request -> mapped to permission
    perm_d = date(2026, 11, 15)
    perm_leave = LeaveRequest.objects.create(
        employee=employee, request_type='PERMISSION', start_date=perm_d, end_date=perm_d, duration_hours=2.0, reason='Early departure'
    )
    res_perm = client.post(PREFIX + 'leave-action/', {'request_id': perm_leave.pk, 'action': 'APPROVED'})
    assert res_perm.status_code == 200
    rec_perm = PayrollAttendance.objects.get(employee=payroll, date=perm_d)
    assert rec_perm.status == AttendanceStatus.permission


def test_me_endpoint_exposes_employee_effective_shift_timing(accounts):
    """Regression: the kiosk's /me/ endpoint (fetched right after login/registration) must
    expose the resolved cutoff/checkout time that actually applies to this employee, so the
    kiosk UI's late-arrival warning and 'Your Shift' banner stop hardcoding 09:30/10:00/18:00
    and instead reflect the employee's own assigned shift when the company enables it."""
    owner, payroll, employee = accounts[0]
    company = Company.objects.get(user=owner)

    # Feature disabled (default): /me/ reflects the company's own default timing.
    response = session_client(employee).get(PREFIX + 'me/')
    assert response.status_code == 200
    assert response.data['effective_start_time'] == '09:30'
    assert response.data['effective_end_time'] == '18:00'
    assert response.data['effective_timing'] == '09:30 AM - 06:00 PM'

    # Feature enabled with a custom shift: /me/ reflects the employee's own shift instead.
    payroll.shift_start_time = '11:00'
    payroll.shift_end_time = '17:00'
    payroll.save()
    company.enable_employee_shift_timing = True
    company.save()

    response2 = session_client(employee).get(PREFIX + 'me/')
    assert response2.status_code == 200
    assert response2.data['effective_start_time'] == '11:00'
    assert response2.data['effective_end_time'] == '17:00'
    assert response2.data['effective_timing'] == '11:00 AM - 05:00 PM'


def test_half_days_first_also_exhaust_the_shared_weekoff_pool(accounts):
    """The monthly Weekoff pool is shared: 2 half-days (1 unit each) consumed first leave
    no units for a later full-day leave, which then deducts the full 1.0 day (no partial credit)."""
    from app.models.attendance import Attendance as PayrollAttendance, AttendanceStatus
    owner, payroll, employee = accounts[0]
    client = APIClient()
    client.force_authenticate(user=owner)

    # 1st half-day (uses 1 of 2 units) -> free
    half_d1 = date(2026, 11, 3)
    hd1 = LeaveRequest.objects.create(
        employee=employee, request_type='HALF_DAY', start_date=half_d1, end_date=half_d1, reason='Doctor'
    )
    r1 = client.post(PREFIX + 'leave-action/', {'request_id': hd1.pk, 'action': 'APPROVED'})
    assert r1.status_code == 200
    assert PayrollAttendance.objects.get(employee=payroll, date=half_d1).status == AttendanceStatus.weekoff_halfday

    # 2nd half-day (uses the last unit) -> still free
    half_d2 = date(2026, 11, 5)
    hd2 = LeaveRequest.objects.create(
        employee=employee, request_type='HALF_DAY', start_date=half_d2, end_date=half_d2, reason='Doctor 2'
    )
    r2 = client.post(PREFIX + 'leave-action/', {'request_id': hd2.pk, 'action': 'APPROVED'})
    assert r2.status_code == 200
    assert PayrollAttendance.objects.get(employee=payroll, date=half_d2).status == AttendanceStatus.weekoff_halfday

    # A full-day leave afterwards needs 2 units but 0 remain -> deducts the full 1.0 day.
    full_d = date(2026, 11, 10)
    full_leave = LeaveRequest.objects.create(
        employee=employee, request_type='CASUAL', start_date=full_d, end_date=full_d, reason='Trip'
    )
    r3 = client.post(PREFIX + 'leave-action/', {'request_id': full_leave.pk, 'action': 'APPROVED'})
    assert r3.status_code == 200
    assert PayrollAttendance.objects.get(employee=payroll, date=full_d).status == AttendanceStatus.leave


def test_mark_attendance_uses_employee_shift_cutoff_only_when_company_enables_it(accounts, monkeypatch):
    owner, payroll, employee = accounts[0]
    payroll.date_of_joining = date(2020, 1, 1)
    payroll.shift_start_time = '11:00'
    payroll.save()

    monkeypatch.setattr('attendance.secure_views.encode_photo', lambda _: [0.1] * 128)
    fixed_now = timezone.make_aware(datetime(2026, 11, 2, 10, 0, 0))
    monkeypatch.setattr('attendance.secure_views.timezone.localtime', lambda: fixed_now)
    punch = {'latitude': 8.78, 'longitude': 78.11, 'face_image': SimpleUploadedFile('p.jpg', b'x', content_type='image/jpeg')}

    # Feature disabled (default): company's 09:30 default cutoff applies -> 10:00 AM is LATE,
    # even though the employee has their own (later) shift_start_time set.
    company = Company.objects.get(user=owner)
    assert company.enable_employee_shift_timing is False
    response = session_client(employee).post(PREFIX + 'mark-attendance/', punch, format='multipart')
    assert response.status_code == 201
    assert response.data['status'] == 'LATE'

    Attendance.objects.filter(employee=employee).delete()

    # Feature enabled: the employee's own 11:00 AM cutoff applies -> 10:00 AM is PRESENT.
    company.enable_employee_shift_timing = True
    company.save()
    response2 = session_client(employee).post(PREFIX + 'mark-attendance/', punch, format='multipart')
    assert response2.status_code == 201
    assert response2.data['status'] == 'PRESENT'


def test_monthly_attendance_is_late_flag_respects_bio_status_only(accounts):
    """Regression: the Attendance & Leave Management page's is_late flag must come from
    the punch's own stored status (already correct for the company default or a
    per-employee shift cutoff), not a separate hardcoded 10 AM threshold that would
    contradict an employee whose own shift starts later than 10 AM."""
    owner, payroll, employee = accounts[0]
    today = date.today()
    # 10:30 AM check-in: the old hardcoded "> 10 AM" check would have flagged this as
    # late regardless of the employee's own shift - but the stored status (as computed
    # correctly at punch time) says PRESENT, so the summary must agree.
    Attendance.objects.create(
        employee=employee, check_in=time(10, 30), status='PRESENT',
        punch_latitude=8.78, punch_longitude=78.11, distance_meters=0,
    )
    client = APIClient()
    client.force_authenticate(user=owner)
    response = client.get(f"/api/v1/attendance/monthly?employee_id={payroll.id}&month={today.month}&year={today.year}")
    assert response.status_code == 200
    row = next(r for r in response.json() if r["date"] == str(today))
    assert row["is_late"] is False
    assert row["status"] == "present"


def test_permission_allowance_and_excess_deduction(accounts):
    from app.services.attendance_service import bulk_mark_leaves, get_all_employees_leave_summary
    from app.services.salary_service import generate_slip_for_employee
    owner, payroll, _ = accounts[0]
    payroll.date_of_joining = date(2026, 1, 1)
    payroll.basic_salary = 30000
    payroll.save()

    # 1. Exactly 3 permissions in November 2026 (30 days total) -> 0 deduction
    bulk_mark_leaves(
        None, owner, payroll.id, 11, 2026,
        leave_dates=[],
        permission_dates=[date(2026, 11, 2), date(2026, 11, 3), date(2026, 11, 4)]
    )
    summary = get_all_employees_leave_summary(None, owner, 11, 2026)
    emp_s = [s for s in summary if s['employee_id'] == payroll.id][0]
    assert emp_s['permission_days'] == 3
    assert emp_s['leave_deduction'] == 0.0

    slip = generate_slip_for_employee(None, owner, payroll, 11, 2026)
    assert float(slip.leave_deduction) == 0.0

    # 2. 4 permissions -> excess 1 permission = 1 day leave deduction
    # 30000 / 30 * 1 = 1000.0
    bulk_mark_leaves(
        None, owner, payroll.id, 11, 2026,
        leave_dates=[],
        permission_dates=[date(2026, 11, 2), date(2026, 11, 3), date(2026, 11, 4), date(2026, 11, 5)]
    )
    summary2 = get_all_employees_leave_summary(None, owner, 11, 2026)
    emp_s2 = [s for s in summary2 if s['employee_id'] == payroll.id][0]
    assert emp_s2['permission_days'] == 4
    assert emp_s2['leave_deduction'] == 1000.0


def test_permission_step_out_and_return_cycle(accounts, monkeypatch):
    """A step-out under an approved PERMISSION, followed by a return punch, keeps the
    day's single Attendance row open (no check_out) until the real end-of-day checkout,
    and the worked-hours calc excludes the permission gap."""
    owner, payroll, employee = accounts[0]
    payroll.date_of_joining = date(2020, 1, 1)
    payroll.save()

    monkeypatch.setattr('attendance.secure_views.encode_photo', lambda _: [0.1] * 128)
    client = session_client(employee)
    punch = lambda: {'latitude': 8.78, 'longitude': 78.11, 'face_image': SimpleUploadedFile('p.jpg', b'x', content_type='image/jpeg')}
    # date is auto_now_add, so it always lands on the real current date regardless of the
    # timezone.localtime() mock below (which only controls the time-of-day decisions).
    today = date.today()
    Attendance.objects.filter(employee=employee, date=today).delete()

    def at(h, m):
        fixed_now = timezone.make_aware(datetime(today.year, today.month, today.day, h, m, 0))
        monkeypatch.setattr('attendance.secure_views.timezone.localtime', lambda: fixed_now)

    # 1. Check-in at 09:00
    at(9, 0)
    r1 = client.post(PREFIX + 'mark-attendance/', punch(), format='multipart')
    assert r1.status_code == 201 and r1.data['type'] == 'CHECK_IN'

    # 2. Approved 2-hour permission for today
    LeaveRequest.objects.create(
        employee=employee, request_type='PERMISSION', start_date=today, end_date=today,
        duration_hours=2.0, status='APPROVED', reason='Bank work',
    )

    # 3. Step-out at 12:00 (returns by 14:00, well before the 18:00 default boundary)
    at(12, 0)
    r2 = client.post(PREFIX + 'mark-attendance/', punch(), format='multipart')
    assert r2.status_code == 201
    assert r2.data['type'] == 'PERMISSION_OUT'
    record = Attendance.objects.get(employee=employee, date=today)
    assert record.check_out is None
    assert str(record.permission_out) == '12:00:00'

    # 4. Return at 13:00
    at(13, 0)
    r3 = client.post(PREFIX + 'mark-attendance/', punch(), format='multipart')
    assert r3.status_code == 201
    assert r3.data['type'] == 'PERMISSION_IN'
    record.refresh_from_db()
    assert record.check_out is None
    assert str(record.permission_in) == '13:00:00'

    # 5. Final checkout at 18:30 (after the 18:00 boundary)
    at(18, 30)
    r4 = client.post(PREFIX + 'mark-attendance/', punch(), format='multipart')
    assert r4.status_code == 201
    assert r4.data['type'] == 'PUNCH_OUT'
    record.refresh_from_db()
    assert record.check_out is not None

    # 6. Monthly summary's worked hours exclude the 1-hour permission gap:
    # 09:00 -> 18:30 = 9.5h, minus the 12:00-13:00 (1h) gap = 8.5h.
    from app.services.attendance_service import get_monthly_attendance
    rows = get_monthly_attendance(None, owner, payroll.id, today.month, today.year)
    row = next(r for r in rows if r['date'] == today)
    assert row['duration_hours'] == 8.5
    assert row['permission_out'] == '12:00 PM'
    assert row['permission_in'] == '01:00 PM'


def test_permission_step_out_without_approval_is_rejected(accounts, monkeypatch):
    owner, payroll, employee = accounts[0]
    payroll.date_of_joining = date(2020, 1, 1)
    payroll.save()
    monkeypatch.setattr('attendance.secure_views.encode_photo', lambda _: [0.1] * 128)
    client = session_client(employee)
    punch = lambda: {'latitude': 8.78, 'longitude': 78.11, 'face_image': SimpleUploadedFile('p.jpg', b'x', content_type='image/jpeg')}
    today = date.today()
    Attendance.objects.filter(employee=employee, date=today).delete()

    def at(h, m):
        fixed_now = timezone.make_aware(datetime(today.year, today.month, today.day, h, m, 0))
        monkeypatch.setattr('attendance.secure_views.timezone.localtime', lambda: fixed_now)

    at(9, 0)
    assert client.post(PREFIX + 'mark-attendance/', punch(), format='multipart').status_code == 201
    at(12, 0)
    r = client.post(PREFIX + 'mark-attendance/', punch(), format='multipart')
    assert r.status_code == 403


def test_permission_reaching_shift_end_becomes_final_checkout(accounts, monkeypatch):
    """If the permission's duration would run past the shift's checkout boundary, there's
    no time left to return - so the step-out punch becomes the real final checkout, not a
    PERMISSION_OUT (otherwise the missed-checkout detector would wrongly flag it later)."""
    owner, payroll, employee = accounts[0]
    payroll.date_of_joining = date(2020, 1, 1)
    payroll.save()
    monkeypatch.setattr('attendance.secure_views.encode_photo', lambda _: [0.1] * 128)
    client = session_client(employee)
    punch = lambda: {'latitude': 8.78, 'longitude': 78.11, 'face_image': SimpleUploadedFile('p.jpg', b'x', content_type='image/jpeg')}
    today = date.today()
    Attendance.objects.filter(employee=employee, date=today).delete()

    def at(h, m):
        fixed_now = timezone.make_aware(datetime(today.year, today.month, today.day, h, m, 0))
        monkeypatch.setattr('attendance.secure_views.timezone.localtime', lambda: fixed_now)

    at(9, 0)
    assert client.post(PREFIX + 'mark-attendance/', punch(), format='multipart').status_code == 201
    LeaveRequest.objects.create(
        employee=employee, request_type='PERMISSION', start_date=today, end_date=today,
        duration_hours=8.0, status='APPROVED', reason='Long errand',
    )
    at(12, 0)  # 12:00 + 8h = 20:00, past the 18:00 default boundary - no time to return.
    r = client.post(PREFIX + 'mark-attendance/', punch(), format='multipart')
    assert r.status_code == 201
    assert r.data['type'] == 'PUNCH_OUT'
    record = Attendance.objects.get(employee=employee, date=today)
    assert record.check_out is not None
    assert record.permission_out is None


