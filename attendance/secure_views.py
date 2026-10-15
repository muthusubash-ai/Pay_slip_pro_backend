import math
import secrets
from datetime import date, time

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import (
    AuthenticationFailed,
    PermissionDenied,
    ValidationError,
)
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from app.auth.authentication import JWTAuthentication
from app.models.company import Company

from .models import Attendance, Employee, EmployeeSession, LeaveRequest
from .payroll_sync import get_monthly_payroll_summary
from .security import (
    COOKIE,
    COOKIE_PATH,
    AccountLoginThrottle,
    AttendanceThrottle,
    EmployeeAuthentication,
    LoginThrottle,
    PhotoThrottle,
    check_password_strength,
    digest,
    encode_photo,
    get_invite,
    set_session,
)
from .services import evaluate_attendance_status, haversine_distance


def _parse_hhmm(value, fallback):
    if value:
        try:
            parts = [int(p) for p in str(value).split(':')]
            return time(parts[0], parts[1] if len(parts) > 1 else 0)
        except Exception:
            pass
    return fallback


def effective_shift_times(payroll, company):
    """Resolve the cutoff (late-arrival) and checkout-boundary times that actually apply
    to this employee: the company default, overridden by the employee's own
    shift_start_time/shift_end_time when the company has enabled that feature."""
    cutoff = _parse_hhmm(company.office_start_time if company else None, time(9, 30))
    checkout_boundary = _parse_hhmm(company.office_end_time if company else None, time(18))
    if company and company.enable_employee_shift_timing:
        cutoff = _parse_hhmm(payroll.shift_start_time, cutoff)
        checkout_boundary = _parse_hhmm(payroll.shift_end_time, checkout_boundary)
    return cutoff, checkout_boundary


def company_data(payroll=None, company=None):
    if company is None and payroll is not None:
        company = getattr(payroll.user, 'company', None)
    if company is None:
        company = (
            Company.objects.filter(Q(logo_data__isnull=False) | Q(logo_url__isnull=False))
            .order_by('-updated_at')
            .first()
            or Company.objects.order_by('-updated_at').first()
        )
    return {
        'company_name': company.company_name if company else 'Zigmaa Tech',
        'office_name': company.company_name if company else 'Zigmaa Tech',
        'company_logo': (company.logo_data or company.logo_url) if company else '',
        'logo_data': company.logo_data if company else '',
        'logo_url': company.logo_url if company else '',
        'primary_color': company.primary_color if (company and company.primary_color) else '#4f46e5',
        'address': company.address if (company and company.address) else '',
        'office_lat': company.office_lat if (company and company.office_lat is not None) else 8.7892563,
        'office_lng': company.office_lng if (company and company.office_lng is not None) else 78.117146,
        'allowed_radius_meters': company.allowed_radius_meters if (company and company.allowed_radius_meters is not None) else 70,
        'office_timing': company.office_timing if (company and company.office_timing) else '09:30 AM - 06:00 PM',
        'office_start_time': company.office_start_time if (company and company.office_start_time) else '09:30',
        'office_end_time': company.office_end_time if (company and company.office_end_time) else '18:00',
    }


def profile(employee):
    payroll = employee.payroll_employee
    company = getattr(payroll.user, 'company', None)
    c_info = company_data(payroll, company)
    cutoff, checkout_boundary = effective_shift_times(payroll, company)
    return {
        'emp_id': employee.emp_id,
        'full_name': payroll.full_name,
        'email': employee.email,
        'designation': payroll.designation or '',
        'phone_number': employee.phone_number or '',
        'joining_date': str(payroll.date_of_joining),
        'company_name': c_info.get('company_name', ''),
        'company_logo': c_info.get('company_logo', ''),
        'company_data': c_info,
        # The cutoff/checkout times actually enforced for THIS employee - the company
        # default, or their own shift_start_time/shift_end_time when the company has
        # enabled per-employee shift timing. The kiosk uses these instead of a
        # hardcoded time so the late-arrival warning matches what punch-in will record.
        'effective_start_time': cutoff.strftime('%H:%M'),
        'effective_end_time': checkout_boundary.strftime('%H:%M'),
        'effective_timing': f"{cutoff.strftime('%I:%M %p')} - {checkout_boundary.strftime('%I:%M %p')}",
    }


class PublicView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [AttendanceThrottle]

    def get_authenticate_header(self, request):
        return 'Bearer'

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        JWTAuthentication._enforce_csrf(request)


class EmployeeView(APIView):
    authentication_classes = [EmployeeAuthentication]
    permission_classes = [IsAuthenticated]
    throttle_classes = [AttendanceThrottle]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        claimed = request.query_params.get('emp_id') if request.method == 'GET' else request.data.get('emp_id')
        if claimed and str(claimed).lower() != request.user.emp_id.lower():
            raise PermissionDenied('You can access only your own attendance account.')


class EmployeeLoginView(PublicView):
    throttle_classes = [LoginThrottle, AccountLoginThrottle]

    def post(self, request):
        identifier = str(request.data.get('identifier', '')).strip()
        password = request.data.get('password', '')
        employees = list(Employee.objects.select_related('payroll_employee__user').filter(
            Q(email__iexact=identifier) | Q(emp_id__iexact=identifier), is_active=True,
            payroll_employee__is_active=True, payroll_employee__user__is_active=True)[:2])
        if len(employees) != 1 or not isinstance(password, str) or len(password) > 256 or employees[0].email.lower() != employees[0].payroll_employee.email.lower() or not employees[0].check_password(password):
            raise AuthenticationFailed('Invalid credentials or inactive account. Use your email to sign in.')
        return set_session(Response(profile(employees[0])), employees[0])


class AttendanceForgotPasswordView(PublicView):
    throttle_classes = [LoginThrottle, AccountLoginThrottle]

    def post(self, request):
        identifier = str(request.data.get('identifier', '')).strip()
        if not identifier:
            raise ValidationError('Email or Employee ID is required.')

        employees = list(Employee.objects.select_related('payroll_employee__user').filter(
            Q(email__iexact=identifier) | Q(emp_id__iexact=identifier),
            is_active=True,
            payroll_employee__is_active=True,
            payroll_employee__user__is_active=True,
        )[:2])

        if len(employees) > 1:
            return Response(
                {"detail": "Multiple accounts found with this Employee ID. Please enter your registered email address.", "sent": False},
                status=400,
            )
        if len(employees) == 0 or not employees[0].email or employees[0].email.lower() != employees[0].payroll_employee.email.lower():
            return Response(
                {"detail": "This employee account is not registered or active. Please check your credentials.", "sent": False},
                status=400,
            )

        employee = employees[0]
        code = f"{secrets.randbelow(900000) + 100000}"
        code_digest = digest(code)
        cache_key = f"attendance_reset:{employee.email.lower()}"
        cache.set(cache_key, code_digest, timeout=900)

        from app.services.email_service import send_password_reset_email
        sent = send_password_reset_email(employee.email, code)
        if sent:
            return Response({
                "message": "Reset code sent to your email. Check your inbox.",
                "sent": True,
                "email": employee.email,
            })
        return Response(
            {"detail": "Failed to send reset code email. Please check email service configuration.", "sent": False},
            status=500,
        )


class AttendanceResetPasswordView(PublicView):
    throttle_classes = [LoginThrottle, AccountLoginThrottle]

    def post(self, request):
        identifier = str(request.data.get('identifier', '')).strip()
        code = str(request.data.get('code', '')).strip()
        new_password = request.data.get('new_password', '')

        if not identifier or not code or not new_password:
            raise ValidationError('Identifier, reset code, and new password are required.')

        employees = list(Employee.objects.select_related('payroll_employee__user').filter(
            Q(email__iexact=identifier) | Q(emp_id__iexact=identifier),
            is_active=True,
            payroll_employee__is_active=True,
            payroll_employee__user__is_active=True,
        )[:2])

        if len(employees) > 1:
            raise ValidationError('Multiple accounts found with this Employee ID. Please use your registered email address.')

        if len(employees) == 0 or not employees[0].email:
            raise ValidationError('Employee account not found or inactive.')

        employee = employees[0]
        cache_key = f"attendance_reset:{employee.email.lower()}"
        stored_digest = cache.get(cache_key)

        if not stored_digest:
            raise ValidationError('Reset code is missing or expired. Please request a new one.')

        if not secrets.compare_digest(stored_digest, digest(code)):
            raise ValidationError('Invalid reset code.')

        check_password_strength(new_password, employee)

        with transaction.atomic():
            emp_obj = Employee.objects.select_for_update().get(pk=employee.pk)
            emp_obj.set_password(new_password)
            emp_obj.save(update_fields=['password'])
            EmployeeSession.objects.filter(employee=emp_obj).delete()

        cache.delete(cache_key)
        return Response({
            "message": "Password reset successful! You can now login with your new password.",
            "success": True,
        })



class MeView(EmployeeView):
    def get(self, request):
        return Response(profile(request.user), headers={'Cache-Control': 'no-store'})


class LogoutView(EmployeeView):
    def post(self, request):
        request.auth.delete()
        response = Response({'message': 'Signed out.'})
        response.delete_cookie(COOKIE, path=COOKIE_PATH, samesite=settings.AUTH_COOKIE_SAMESITE)
        return response


class GoogleNonceView(PublicView):
    def get(self, request):
        if not settings.GOOGLE_CLIENT_ID:
            return Response({'detail': 'Google sign-in is not configured.'}, status=503)
        nonce = secrets.token_urlsafe(32)
        cache.set('attendance-google:' + nonce, True, 300)
        response = Response({'nonce': nonce, 'client_id': settings.GOOGLE_CLIENT_ID})
        response.set_cookie('attendance_google_nonce', nonce, max_age=300, httponly=True,
                            secure=not settings.DEBUG, samesite=settings.AUTH_COOKIE_SAMESITE, path=COOKIE_PATH)
        response['Cache-Control'] = 'no-store'
        return response


def verify_google_credential(credential):
    from google.auth.transport.requests import Request
    from google.oauth2.id_token import verify_oauth2_token
    transport = Request()
    def request_with_timeout(*args, **kwargs):
        kwargs['timeout'] = 10
        return transport(*args, **kwargs)
    return verify_oauth2_token(credential, request_with_timeout, settings.GOOGLE_CLIENT_ID)


class GoogleLoginView(PublicView):
    throttle_classes = [LoginThrottle]

    def post(self, request):
        credential = request.data.get('credential')
        nonce = request.COOKIES.get('attendance_google_nonce', '')
        if not settings.GOOGLE_CLIENT_ID or not isinstance(credential, str) or len(credential) > 16384 or not nonce:
            raise AuthenticationFailed('Invalid Google sign-in. Please try again.')
        try:
            claims = verify_google_credential(credential)
        except Exception as exc:
            raise AuthenticationFailed('Google identity could not be verified.') from exc
        if claims.get('email_verified') is not True or not claims.get('sub') or not secrets.compare_digest(str(claims.get('nonce', '')), nonce) or not cache.get('attendance-google:' + nonce):
            raise AuthenticationFailed('Invalid or expired Google sign-in.')
        if not cache.add('attendance-google-used:' + nonce, True, 300):
            raise AuthenticationFailed('Google sign-in has already been used.')
        cache.delete('attendance-google:' + nonce)
        with transaction.atomic():
            employee = Employee.objects.select_for_update().filter(email__iexact=claims.get('email', ''), is_active=True,
                payroll_employee__is_active=True, payroll_employee__user__is_active=True).first()
            if not employee or employee.email.lower() != employee.payroll_employee.email.lower() or (employee.google_subject and employee.google_subject != claims['sub']):
                raise AuthenticationFailed('Activate your company invitation before using Google sign-in.')
            employee.google_subject = claims['sub']
            employee.save(update_fields=['google_subject'])
            response = set_session(Response(profile(employee)), employee)
        response.delete_cookie('attendance_google_nonce', path=COOKIE_PATH, samesite=settings.AUTH_COOKIE_SAMESITE)
        return response


class LookupEmployeeView(PublicView):
    def get(self, request):
        payroll = get_invite(request).payroll_employee
        account = Employee.objects.filter(payroll_employee=payroll).first()
        is_already_registered = bool(account and account.password and account.is_active)
        return Response({'found': True, 'emp_id': payroll.employee_code, 'full_name': payroll.full_name,
                         'email': payroll.email, 'designation': payroll.designation or '',
                         'phone_number': payroll.phone or '', 'joining_date': str(payroll.date_of_joining),
                         'already_registered': is_already_registered,
                         **company_data(payroll)}, headers={'Cache-Control': 'no-store'})


class GeofenceConfigView(APIView):
    authentication_classes = [EmployeeAuthentication]
    permission_classes = [AllowAny]
    throttle_classes = [AttendanceThrottle]

    def get(self, request):
        if request.query_params.get('emp_id') and (not getattr(request, 'user', None) or not hasattr(request.user, 'payroll_employee')):
            payroll = get_invite(request).payroll_employee
            return Response(company_data(payroll))

        payroll = None
        if getattr(request, 'user', None) and hasattr(request.user, 'payroll_employee'):
            payroll = request.user.payroll_employee

        if not payroll and request.headers.get('X-Attendance-Invite'):
            try:
                payroll = get_invite(request).payroll_employee
            except Exception:
                pass

        if not payroll and getattr(request, 'user', None) and hasattr(request.user, 'company'):
            return Response(company_data(company=request.user.company))

        return Response(company_data(payroll=payroll))


class EmployeeRegisterView(PublicView):
    throttle_classes = [PhotoThrottle]
    def post(self, request):
        invitation = get_invite(request)
        password = request.data.get('password', '')
        check_password_strength(password, invitation.payroll_employee)
        vector = encode_photo(request.FILES.get('face_image'))
        with transaction.atomic():
            invitation = get_invite(request, lock=True)
            payroll = invitation.payroll_employee
            employee = Employee.objects.select_for_update().filter(payroll_employee=payroll).first()
            if not employee:
                employee = Employee.objects.select_for_update().filter(email__iexact=invitation.email).first()
                if employee and (employee.payroll_employee_id or employee.emp_id.lower() != payroll.employee_code.lower()):
                    raise ValidationError('This email is already assigned to another attendance account. Contact your administrator.')
            if not employee:
                employee = Employee.objects.select_for_update().filter(emp_id__iexact=payroll.employee_code).first()
            if not employee:
                employee = Employee(email=invitation.email)
            employee.payroll_employee = payroll
            employee.emp_id = payroll.employee_code
            employee.full_name = payroll.full_name
            employee.email = invitation.email
            employee.designation = payroll.designation or ''
            employee.joining_date = payroll.date_of_joining
            employee.phone_number = payroll.phone
            employee.face_encoding = vector
            employee.is_active = True
            employee.set_password(password)
            employee.save()
            EmployeeSession.objects.filter(employee=employee).delete()
            invitation.used = True
            invitation.save(update_fields=['used'])
            return set_session(Response(profile(employee), status=201), employee)


class VerifyFaceView(PublicView):
    throttle_classes = [PhotoThrottle]
    def post(self, request):
        get_invite(request)
        encode_photo(request.FILES.get('face_image'))
        return Response({'valid': True})


class RegisteredDescriptorsView(PublicView):
    def get(self, request):
        return Response({'detail': 'Biometric templates are never published.'}, status=410)


class UpdateProfileView(EmployeeView):
    def post(self, request):
        employee = request.user
        # Identity, email, designation and joining date belong to the company record.
        password = request.data.get('new_password')
        if password:
            if not employee.check_password(request.data.get('current_password', '')):
                raise PermissionDenied('Enter your current password to change it.')
            check_password_strength(password, employee)
        phone = str(request.data.get('phone_number', employee.phone_number or '')).strip()
        if phone and (not phone.isdigit() or len(phone) != 10):
            raise ValidationError('Phone number must contain 10 digits.')
        with transaction.atomic():
            employee = Employee.objects.select_for_update().get(pk=employee.pk)
            if password:
                if not employee.check_password(request.data.get('current_password', '')):
                    raise PermissionDenied('Current password is incorrect.')
                employee.set_password(password)
                EmployeeSession.objects.filter(employee=employee).delete()
            employee.phone_number = phone
            employee.save()
            response = Response(profile(employee))
            return set_session(response, employee) if password else response


class MarkAttendanceView(EmployeeView):
    throttle_classes = [PhotoThrottle]
    def post(self, request):
        employee = request.user
        payroll = employee.payroll_employee
        company = getattr(payroll.user, 'company', None)
        if not company or company.office_lat is None or company.office_lng is None or not company.allowed_radius_meters or company.allowed_radius_meters < 1:
            raise ValidationError('Your administrator must configure the office location first.')
        try:
            lat, lng = float(request.data['latitude']), float(request.data['longitude'])
            if not math.isfinite(lat) or not math.isfinite(lng) or not -90 <= lat <= 90 or not -180 <= lng <= 180:
                raise ValueError()
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError('Valid location coordinates are required.') from exc
        distance = haversine_distance(float(company.office_lat), float(company.office_lng), lat, lng)
        if distance > company.allowed_radius_meters:
            raise PermissionDenied('Attendance is allowed only within the configured office area.')
        captured = encode_photo(request.FILES.get('face_image'))
        stored = employee.face_encoding
        if not stored or len(stored) != 128 or math.dist(stored, captured) > 0.48:
            raise PermissionDenied('Face verification failed. Ask your administrator for a new invitation if re-enrollment is needed.')
        now = timezone.localtime()
        today = now.date()
        if today < payroll.date_of_joining:
            raise ValidationError('Attendance cannot be marked before your joining date.')
        with transaction.atomic():
            Employee.objects.select_for_update().get(pk=employee.pk)
            leave = LeaveRequest.objects.filter(employee=employee, status='APPROVED', start_date__lte=today, end_date__gte=today).first()
            record = Attendance.objects.filter(employee=employee, date=today).first()
            cutoff, checkout_boundary = effective_shift_times(payroll, company)
            if record:
                if record.check_out:
                    raise ValidationError('Attendance for today is already complete.')
                if now.time() < checkout_boundary and (not leave or leave.request_type not in ('PERMISSION', 'HALF_DAY')):
                    raise PermissionDenied('Early checkout requires an approved permission or half-day request.')
                record.check_out = now.time()
                record.save(update_fields=['check_out', 'updated_at'])
                kind = 'PUNCH_OUT'
            else:
                record = Attendance.objects.create(employee=employee, check_in=now.time(), status=evaluate_attendance_status(now.time(), leave, today.weekday() == 6, cutoff_time=cutoff), punch_latitude=lat, punch_longitude=lng, distance_meters=distance)
                kind = 'CHECK_IN'
        return Response({'message': 'Attendance recorded.', 'type': kind, 'status': record.status, 'employee_name': payroll.full_name,
                         'emp_id': employee.emp_id, 'check_in': str(record.check_in), 'check_out': str(record.check_out or ''), 'distance': f'{distance:.1f}m'}, status=201)


class AttendanceHistoryView(EmployeeView):
    def get(self, request):
        return Response([{'id': a.id, 'emp_id': request.user.emp_id, 'employee_name': request.user.full_name,
            'date': str(a.date), 'check_in': str(a.check_in or ''), 'check_out': str(a.check_out or ''),
            'status': a.status, 'distance': f'{a.distance_meters:.1f}m'} for a in Attendance.objects.filter(employee=request.user)[:400]])


def month_year(request):
    values = request.query_params if request.method == 'GET' else request.data
    try:
        month, year = int(values.get('month', timezone.now().month)), int(values.get('year', timezone.now().year))
        date(year, month, 1)
        if not 2000 <= year <= 2100:
            raise ValueError()
        return month, year
    except (ValueError, TypeError) as exc:
        raise ValidationError('Select a valid month and year.') from exc


class MonthlySummaryView(EmployeeView):
    def get(self, request):
        month, year = month_year(request)
        return Response(get_monthly_payroll_summary(request.user, year, month))


def leave_data(leave):
    return {'id': leave.id, 'emp_id': leave.employee.emp_id, 'employee_name': leave.employee.full_name,
            'request_type': leave.request_type, 'start_date': str(leave.start_date), 'end_date': str(leave.end_date),
            'duration_hours': leave.duration_hours, 'reason': leave.reason, 'status': leave.status,
            'admin_remarks': leave.admin_remarks or '', 'created_at': leave.created_at.isoformat()}


class SubmitLeaveRequestView(EmployeeView):
    def post(self, request):
        kind = request.data.get('request_type', '')
        try:
            start, end = date.fromisoformat(request.data.get('start_date', '')), date.fromisoformat(request.data.get('end_date', ''))
            hours = float(request.data.get('duration_hours') or 0)
        except (TypeError, ValueError) as exc:
            raise ValidationError('Enter valid leave dates and hours.') from exc
        reason = str(request.data.get('reason', '')).strip()
        if kind not in dict(LeaveRequest.TYPE_CHOICES) or not reason or len(reason) > 2000 or start < request.user.payroll_employee.date_of_joining or end < start or (end-start).days > 366:
            raise ValidationError('Enter a valid request type, reason and date range.')
        if kind == 'HALF_DAY' and start != end:
            raise ValidationError('Half-day leave must be for a single date.')
        if kind == 'PERMISSION' and (start != end or not math.isfinite(hours) or not 0 < hours <= 8):
            raise ValidationError('Permission must be for one date and between 0 and 8 hours.')
        leave = LeaveRequest.objects.create(employee=request.user, request_type=kind, start_date=start, end_date=end, duration_hours=hours if kind == 'PERMISSION' else None, reason=reason)
        from app.services.email_service import send_leave_request_notification_email
        payroll = request.user.payroll_employee
        try:
            send_leave_request_notification_email(to_email=payroll.user.email, employee_name=payroll.full_name,
                employee_email=request.user.email, request_type=kind, start_date=str(start), end_date=str(end),
                duration_hours=leave.duration_hours, reason=reason, request_id=leave.pk, company_name=payroll.user.company_name)
        except Exception:
            import logging
            logging.getLogger(__name__).warning('Leave notification delivery failed for request %s', leave.pk)
        return Response(leave_data(leave), status=201)


class MyLeaveRequestsView(EmployeeView):
    def get(self, request):
        return Response({'leave_requests': [leave_data(x) for x in LeaveRequest.objects.filter(employee=request.user)[:200]]})


class OwnerView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]
    throttle_classes = [AttendanceThrottle]


class LeaveActionView(OwnerView):
    def get(self, request):
        if getattr(request.user, 'is_platform_admin', False) or getattr(request.user, 'is_superuser', False):
            rows = list(LeaveRequest.objects.select_related('employee__payroll_employee').all().order_by('-created_at')[:200])
        else:
            user_company = getattr(request.user, 'company', None)
            user_emp_codes = list(request.user.employees.values_list('employee_code', flat=True))
            q = (
                Q(employee__payroll_employee__user=request.user) |
                Q(employee__payroll_employee__isnull=True, employee__emp_id__in=user_emp_codes)
            )
            if user_company:
                q |= Q(employee__payroll_employee__user__company=user_company)
            rows = list(LeaveRequest.objects.select_related('employee__payroll_employee').filter(q).order_by('-created_at')[:200])

        # Auto-link unlinked attendance employee if matching payroll employee exists
        for row in rows:
            if row.employee and not row.employee.payroll_employee:
                from app.models.employee import Employee as PayrollEmployee
                pe = PayrollEmployee.objects.filter(user=request.user, employee_code__iexact=row.employee.emp_id).first()
                if pe:
                    row.employee.payroll_employee = pe
                    row.employee.save(update_fields=['payroll_employee'])

        return Response({'leave_requests': [leave_data(x) for x in rows]})

    def post(self, request):
        action = request.data.get('action')
        if action not in ('APPROVED', 'REJECTED'):
            raise ValidationError('Select APPROVED or REJECTED.')
        try:
            request_id = int(request.data.get('request_id', ''))
        except (ValueError, TypeError) as exc:
            raise ValidationError('Select a valid leave request.') from exc
        with transaction.atomic():
            if getattr(request.user, 'is_platform_admin', False) or getattr(request.user, 'is_superuser', False):
                leave_exists = LeaveRequest.objects.filter(pk=request_id).exists()
            else:
                user_company = getattr(request.user, 'company', None)
                user_emp_codes = list(request.user.employees.values_list('employee_code', flat=True))
                q = (
                    Q(employee__payroll_employee__user=request.user) |
                    Q(employee__payroll_employee__isnull=True, employee__emp_id__in=user_emp_codes)
                )
                if user_company:
                    q |= Q(employee__payroll_employee__user__company=user_company)
                leave_exists = LeaveRequest.objects.filter(q, pk=request_id).exists()

            if not leave_exists:
                raise PermissionDenied('Leave request is unavailable.')

            leave = LeaveRequest.objects.select_for_update().filter(pk=request_id).first()

            # Auto-link unlinked attendance employee if matching payroll employee exists
            if leave.employee and not leave.employee.payroll_employee:
                from app.models.employee import Employee as PayrollEmployee
                pe = PayrollEmployee.objects.filter(employee_code__iexact=leave.employee.emp_id).first()
                if pe:
                    leave.employee.payroll_employee = pe
                    leave.employee.save(update_fields=['payroll_employee'])

            if leave.status != 'PENDING':
                raise ValidationError('This request has already been reviewed.')
            leave.status = action
            leave.admin_remarks = str(request.data.get('admin_remarks', ''))[:2000]
            leave.save(update_fields=['status', 'admin_remarks', 'updated_at'])

            if action == 'APPROVED':
                from datetime import timedelta
                from app.models.attendance import Attendance as PayrollAttendance, AttendanceStatus
                from app.models.salary_slip import SalarySlip
                from app.services.attendance_service import (
                    get_leave_count, get_half_day_count, get_permission_count, calculate_leave_deduction,
                    get_weekly_off_weekdays, get_permission_allowance, WEEKOFF_POOL_UNITS_PER_MONTH,
                )

                payroll_emp = getattr(leave.employee, 'payroll_employee', None)
                weekly_off_weekdays = get_weekly_off_weekdays(payroll_emp.user) if payroll_emp else set()
                permission_allowance = get_permission_allowance(payroll_emp.user) if payroll_emp else 3
                curr_date = leave.start_date
                affected_months = set()

                while curr_date <= leave.end_date:
                    d = curr_date
                    m, y = d.month, d.year
                    affected_months.add((m, y))

                    if payroll_emp and payroll_emp.date_of_joining and d < payroll_emp.date_of_joining:
                        curr_date += timedelta(days=1)
                        continue

                    # Attendance Status Hierarchy:
                    # Present -> Leave -> Half Day -> Permission -> Weekoff -> Weekoff Half
                    # Rule: the monthly Weekoff is a single shared pool worth 2 half-day units.
                    # A full-day leave costs 2 units, a half-day leave costs 1 unit - whichever
                    # comes first chronologically draws from the pool first, no partial credit.
                    # The company's configured weekly off day (e.g. every Sunday) always wins and
                    # never consumes that monthly pool.
                    if d.weekday() in weekly_off_weekdays:
                        target_status = AttendanceStatus.company_week_off
                    else:
                        if payroll_emp:
                            existing_weekoff = PayrollAttendance.objects.filter(
                                employee=payroll_emp,
                                date__month=m,
                                date__year=y,
                                status=AttendanceStatus.weekoff
                            ).count()
                            existing_weekoff_half = PayrollAttendance.objects.filter(
                                employee=payroll_emp,
                                date__month=m,
                                date__year=y,
                                status=AttendanceStatus.weekoff_halfday
                            ).count()
                            remaining_units = max(
                                0,
                                WEEKOFF_POOL_UNITS_PER_MONTH - (existing_weekoff * 2 + existing_weekoff_half)
                            )
                        else:
                            remaining_units = 0

                        if leave.request_type in ('CASUAL', 'SICK', 'LEAVE'):
                            if remaining_units >= 2:
                                target_status = AttendanceStatus.weekoff
                            else:
                                target_status = AttendanceStatus.leave
                        elif leave.request_type == 'HALF_DAY':
                            if remaining_units >= 1:
                                target_status = AttendanceStatus.weekoff_halfday
                            else:
                                target_status = AttendanceStatus.half_day
                        elif leave.request_type == 'PERMISSION':
                            target_status = AttendanceStatus.permission
                        else:
                            target_status = AttendanceStatus.leave

                    if payroll_emp:
                        PayrollAttendance.objects.update_or_create(
                            employee=payroll_emp,
                            date=d,
                            defaults={
                                'user': payroll_emp.user,
                                'status': target_status,
                            }
                        )

                    bio_status = 'PRESENT'
                    if target_status in (AttendanceStatus.leave, AttendanceStatus.weekoff):
                        bio_status = 'ABSENT'
                    elif target_status in (AttendanceStatus.half_day, AttendanceStatus.weekoff_halfday):
                        bio_status = 'HALF_DAY'
                    elif target_status == AttendanceStatus.permission:
                        bio_status = 'PRESENT'

                    bio_record = Attendance.objects.filter(employee=leave.employee, date=d).first()
                    if bio_record:
                        bio_record.status = bio_status
                        bio_record.save(update_fields=['status', 'updated_at'])

                    curr_date += timedelta(days=1)

                if payroll_emp:
                    try:
                        for (m, y) in affected_months:
                            slip = SalarySlip.objects.filter(employee=payroll_emp, month=m, year=y).first()
                            if slip:
                                l_count = get_leave_count(None, payroll_emp.user, payroll_emp.id, m, y)
                                h_count = get_half_day_count(None, payroll_emp.user, payroll_emp.id, m, y)
                                p_count = get_permission_count(None, payroll_emp.user, payroll_emp.id, m, y)
                                excess_p = max(0, p_count - permission_allowance)
                                eff_leaves = float(l_count) * 1.0 + float(h_count) * 0.5 + float(excess_p) * 1.0
                                ded = calculate_leave_deduction(float(payroll_emp.basic_salary), eff_leaves, m, y)
                                slip.leave_days = int(round(eff_leaves))
                                slip.leave_deduction = ded
                                gross = float(slip.gross_salary)
                                deductions = float(slip.total_deductions)
                                slip.net_pay = round(max(0.0, gross - deductions - ded), 2)
                                slip.save()
                    except Exception:
                        pass
        return Response(leave_data(leave))


class SyncToPayslipProView(OwnerView):
    def post(self, request):
        from app.models.attendance import Attendance as PayrollAttendance
        from app.models.salary_slip import SalarySlip
        employee = Employee.objects.filter(emp_id=request.data.get('emp_id'), payroll_employee__user=request.user, is_active=True).first()
        if not employee:
            raise PermissionDenied('Employee is unavailable.')
        month, year = month_year(request)
        payroll = employee.payroll_employee
        if SalarySlip.objects.filter(employee=payroll, month=month, year=year).exists():
            raise ValidationError('A salary slip already exists for this month.')
        mapping = {'PRESENT': 'present', 'LATE': 'present', 'HALF_DAY': 'half_day', 'PERMISSION': 'permission', 'LEAVE': 'leave', 'ABSENT': 'leave', 'WEEKOFF_HALF': 'half_day'}
        rows = Attendance.objects.filter(employee=employee, date__month=month, date__year=year, date__gte=payroll.date_of_joining)
        with transaction.atomic():
            for row in rows:
                PayrollAttendance.objects.update_or_create(employee=payroll, date=row.date, defaults={'user': request.user, 'status': mapping.get(row.status, 'leave')})
        return Response({'synced': True, 'records': rows.count(), 'message': 'Recorded attendance synced to payroll.'})
