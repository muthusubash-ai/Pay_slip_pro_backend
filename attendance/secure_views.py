import json
import math
import re
import secrets
from datetime import date, datetime, time, timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError, transaction
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
    face_distance,
    get_invite,
    parse_face_vector,
    set_session,
    extend_session,
)

FACE_MATCH_THRESHOLD = 0.55
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
    shift_start_time/shift_end_time when the company has enabled that feature or when fallback."""
    cutoff = _parse_hhmm(company.office_start_time if company else None, time(9, 30))
    checkout_boundary = _parse_hhmm(company.office_end_time if company else None, time(18))
    if company and company.enable_employee_shift_timing:
        cutoff = _parse_hhmm(payroll.shift_start_time, cutoff)
        checkout_boundary = _parse_hhmm(payroll.shift_end_time, checkout_boundary)
    elif not company and payroll and (payroll.shift_start_time or payroll.shift_end_time):
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
    timing_label = f"{cutoff.strftime('%I:%M %p')} - {checkout_boundary.strftime('%I:%M %p')}"
    if (company and company.enable_employee_shift_timing) or (not company and (payroll.shift_start_time or payroll.shift_end_time)):
        c_info['office_timing'] = timing_label
        c_info['office_start_time'] = cutoff.strftime('%H:%M')
        c_info['office_end_time'] = checkout_boundary.strftime('%H:%M')
    return {
        'emp_id': employee.emp_id,
        'full_name': payroll.full_name,
        'email': employee.email,
        'designation': payroll.designation or '',
        # Payroll is the source of truth, matching full_name/designation/joining_date
        # above - the kiosk's own copy (set at registration, or via UpdateProfileView)
        # is only a fallback for when HR hasn't recorded a phone number in payroll yet.
        'phone_number': payroll.phone or employee.phone_number or '',
        'joining_date': str(payroll.date_of_joining),
        'company_name': c_info.get('company_name', ''),
        'company_logo': c_info.get('company_logo', ''),
        'company_data': c_info,
        'shift_start_time': payroll.shift_start_time or '',
        'shift_end_time': payroll.shift_end_time or '',
        'effective_start_time': cutoff.strftime('%H:%M'),
        'effective_end_time': checkout_boundary.strftime('%H:%M'),
        'effective_timing': timing_label,
    }


def format_punch_time(value):
    """Render a check-in/check-out TimeField as 'hh:mm AM/PM', dropping seconds/microseconds."""
    return value.strftime('%I:%M %p') if value else ''


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
        response = Response(profile(request.user), headers={'Cache-Control': 'no-store'})
        return extend_session(request, response, getattr(request, 'auth', None))


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
        # A valid, unexpired admin invite explicitly authorizes onboarding / face re-enrollment
        is_already_registered = False

        conflict = Employee.objects.filter(email__iexact=payroll.email, is_active=True).first()
        is_email_conflict = bool(
            conflict and conflict.emp_id.lower() != payroll.employee_code.lower()
        )
        email_conflict_error = (
            f'This email is already assigned to another attendance account ({conflict.emp_id} - {conflict.full_name}). Contact your administrator.'
            if is_email_conflict and conflict else ''
        )

        return Response({'found': True, 'emp_id': payroll.employee_code, 'full_name': payroll.full_name,
                         'email': payroll.email, 'designation': payroll.designation or '',
                         'phone_number': payroll.phone or '', 'joining_date': str(payroll.date_of_joining),
                         'gender': '',
                         'already_registered': is_already_registered,
                         'email_conflict': is_email_conflict,
                         'email_conflict_error': email_conflict_error,
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
        invitation = None
        try:
            invitation = get_invite(request)
        except Exception:
            pass

        password = request.data.get('password', '')
        if invitation:
            payroll = invitation.payroll_employee
        else:
            emp_id = str(request.data.get('emp_id', '')).strip()
            email = str(request.data.get('email', '')).strip()
            from app.models.employee import Employee as PayrollEmployee
            payroll = PayrollEmployee.objects.filter(
                Q(email__iexact=email) | Q(employee_code__iexact=emp_id),
                is_active=True
            ).first()

        if not payroll:
            raise PermissionDenied('A valid admin invitation is required. Ask your company administrator to send a new invitation.')

        def find_existing_employee():
            found = Employee.objects.filter(payroll_employee=payroll).first()
            if not found:
                found = Employee.objects.filter(emp_id__iexact=payroll.employee_code).first()
            if not found:
                found = Employee.objects.filter(email__iexact=payroll.email, is_active=True).first()
                if found and found.emp_id.lower() != payroll.employee_code.lower():
                    raise ValidationError(
                        f'This email is already assigned to another attendance account ({found.emp_id} - {found.full_name}). Contact your administrator.'
                    )
            return found

        # Reject duplicate registration without an invitation only if account already has both password AND face:
        precheck = find_existing_employee()
        if not invitation and precheck and precheck.is_active and precheck.password and precheck.face_encoding:
            raise PermissionDenied('This account is already registered. Please log in instead.')

        check_password_strength(password, payroll)
        vector = encode_photo(request.FILES.get('face_image'))
        with transaction.atomic():
            if invitation:
                try:
                    invitation = get_invite(request, lock=True)
                    payroll = invitation.payroll_employee
                except Exception:
                    pass
            employee = Employee.objects.select_for_update().filter(payroll_employee=payroll).first()
            if not employee:
                employee = Employee.objects.select_for_update().filter(emp_id__iexact=payroll.employee_code).first()
            if not employee:
                employee = Employee.objects.select_for_update().filter(email__iexact=payroll.email, is_active=True).first()
                if employee and employee.emp_id.lower() != payroll.employee_code.lower():
                    raise ValidationError(
                        f'This email is already assigned to another attendance account ({employee.emp_id} - {employee.full_name}). Contact your administrator.'
                    )
            if not employee:
                employee = Employee(email=payroll.email)

            if not invitation and employee.is_active and employee.password and employee.face_encoding:
                raise PermissionDenied('This account is already registered. Please log in instead.')

            # What must never happen is two DIFFERENT employees ending up with the
            # same face, so that cross-employee check runs below; a single employee
            # re-registering themselves via a new invite is always allowed.
            #
            # Exclude the current employee's own records completely so re-registration never conflicts:
            other_employees = Employee.objects.filter(
                payroll_employee__user=payroll.user, is_active=True
            ).exclude(face_encoding__isnull=True)
            if getattr(employee, 'pk', None):
                other_employees = other_employees.exclude(pk=employee.pk)
            if getattr(payroll, 'employee_code', None):
                other_employees = other_employees.exclude(emp_id__iexact=payroll.employee_code)
            if getattr(payroll, 'email', None):
                other_employees = other_employees.exclude(email__iexact=payroll.email)
            if getattr(payroll, 'id', None):
                other_employees = other_employees.exclude(payroll_employee=payroll)

            # Use strict 0.20 threshold so different real coworkers (with mobile lighting/camera variations)
            # are never falsely rejected. Only near-identical duplicate photos are caught.
            for other in other_employees:
                other_vector = parse_face_vector(other.face_encoding)
                if other_vector and face_distance(other_vector, vector) <= 0.20:
                    raise PermissionDenied(
                        f'This face is already registered to another employee account: {other.full_name} ({other.emp_id}).'
                    )

            employee.payroll_employee = payroll
            employee.emp_id = payroll.employee_code
            employee.full_name = payroll.full_name
            employee.email = payroll.email
            employee.designation = payroll.designation or ''
            employee.joining_date = payroll.date_of_joining
            employee.phone_number = payroll.phone
            employee.face_encoding = vector
            employee.is_active = True
            employee.set_password(password)
            employee.save()
            EmployeeSession.objects.filter(employee=employee).delete()
            if invitation:
                invitation.used = True
                invitation.save(update_fields=['used'])
            return set_session(Response(profile(employee), status=201), employee)


class VerifyFaceView(PublicView):
    throttle_classes = [PhotoThrottle]
    def post(self, request):
        try:
            get_invite(request)
        except Exception:
            pass
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
        if not payroll:
            from app.models.employee import Employee as PayrollEmployee
            payroll = PayrollEmployee.objects.filter(
                Q(email__iexact=employee.email) | Q(employee_code__iexact=employee.emp_id),
                is_active=True
            ).first()
            if payroll:
                employee.payroll_employee = payroll
                employee.save(update_fields=['payroll_employee'])

        if not payroll or not getattr(payroll, 'user', None):
            raise ValidationError('Your employee profile is not linked to an active company payroll. Please contact your administrator.')

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
        parsed_stored = parse_face_vector(employee.face_encoding)
        if not parsed_stored or len(parsed_stored) != 128:
            raise PermissionDenied('No registered face photo found for your account. Please ask your administrator for a new invitation to enroll your face.')

        dist = face_distance(parsed_stored, captured)
        if dist > FACE_MATCH_THRESHOLD:
            raise PermissionDenied(f'Face verification failed (similarity: {dist:.2f}). Please face the camera directly in good lighting.')

        now = timezone.localtime()
        today = now.date()
        if today < payroll.date_of_joining:
            raise ValidationError('Attendance cannot be marked before your joining date.')
        with transaction.atomic():
            Employee.objects.select_for_update().get(pk=employee.pk)
            leave = LeaveRequest.objects.filter(employee=employee, status='APPROVED', start_date__lte=today, end_date__gte=today).first()
            cutoff, checkout_boundary = effective_shift_times(payroll, company)

            is_night_shift = cutoff > checkout_boundary
            record = None
            if is_night_shift and now.time() < time(14, 0):
                yesterday = today - timedelta(days=1)
                yesterday_record = Attendance.objects.filter(employee=employee, date=yesterday, check_out__isnull=True).first()
                if yesterday_record:
                    record = yesterday_record

            if not record:
                record = Attendance.objects.filter(employee=employee, date=today).first()

            if record:
                if record.check_out:
                    raise ValidationError('Attendance for today is already complete.')

                if record.permission_out and not record.permission_in:
                    # This is the "I'm back" punch after a permission step-out, not a
                    # checkout - the day's record stays open for the real checkout later.
                    record.permission_in = now.time()
                    record.save(update_fields=['permission_in', 'updated_at'])
                    kind = 'PERMISSION_IN'
                else:
                    is_early = False
                    if is_night_shift:
                        if record.date == today and now.time() >= cutoff:
                            is_early = True
                        elif record.date < today and now.time() < checkout_boundary:
                            is_early = True
                    else:
                        if now.time() < checkout_boundary:
                            is_early = True

                    permission_leave = leave if (leave and leave.request_type == 'PERMISSION') else None

                    if is_early and not permission_leave and (not leave or leave.request_type != 'HALF_DAY'):
                        raise PermissionDenied('Early checkout requires an approved permission or half-day request.')

                    step_out = False
                    if is_early and permission_leave and not record.permission_out:
                        # Only a genuine step-and-return if there's actually time left to
                        # come back before the shift ends - otherwise this permission
                        # just runs out the rest of the day, so it's the final checkout
                        # (and the missed-checkout detector must not later flag it).
                        duration = float(permission_leave.duration_hours or 0)
                        return_dt = datetime.combine(today, now.time()) + timedelta(hours=duration)
                        boundary_dt = datetime.combine(today, checkout_boundary)
                        if is_night_shift:
                            boundary_dt += timedelta(days=1)
                        step_out = return_dt < boundary_dt

                    if step_out:
                        record.permission_out = now.time()
                        record.save(update_fields=['permission_out', 'updated_at'])
                        kind = 'PERMISSION_OUT'
                    else:
                        record.check_out = now.time()
                        record.save(update_fields=['check_out', 'updated_at'])
                        kind = 'PUNCH_OUT'
            else:
                try:
                    record = Attendance.objects.create(
                        employee=employee,
                        date=today,
                        check_in=now.time(),
                        status=evaluate_attendance_status(now.time(), leave, today.weekday() == 6, cutoff_time=cutoff),
                        punch_latitude=lat,
                        punch_longitude=lng,
                        distance_meters=distance
                    )
                    kind = 'CHECK_IN'
                except IntegrityError:
                    # A concurrent request for this same employee/day already created
                    # the row between our lookup above and this insert - re-fetch it
                    # instead of surfacing a raw 500 to the kiosk.
                    record = Attendance.objects.filter(employee=employee, date=today).first()
                    if not record:
                        raise
                    raise ValidationError('Attendance for today is already recorded. Please retry.')
        kind_messages = {
            'CHECK_IN': 'Checked in successfully.',
            'PUNCH_OUT': 'Checked out successfully.',
            'PERMISSION_OUT': 'Permission step-out recorded. Punch in when you return.',
            'PERMISSION_IN': 'Welcome back! Permission break ended.',
        }
        response = Response({'message': kind_messages.get(kind, 'Attendance recorded.'), 'type': kind, 'status': record.status, 'employee_name': payroll.full_name,
                         'emp_id': employee.emp_id, 'check_in': format_punch_time(record.check_in), 'check_out': format_punch_time(record.check_out),
                         'permission_out': format_punch_time(record.permission_out), 'permission_in': format_punch_time(record.permission_in),
                         'distance': f'{distance:.1f}m'}, status=201)
        return extend_session(request, response, getattr(request, 'auth', None))


class AttendanceHistoryView(EmployeeView):
    def get(self, request):
        return Response([{'id': a.id, 'emp_id': request.user.emp_id, 'employee_name': request.user.full_name,
            'date': str(a.date), 'check_in': format_punch_time(a.check_in), 'check_out': format_punch_time(a.check_out),
            'permission_out': format_punch_time(a.permission_out), 'permission_in': format_punch_time(a.permission_in),
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
    payroll_emp = getattr(getattr(leave, 'employee', None), 'payroll_employee', None)
    if not payroll_emp and getattr(leave, 'employee', None) and getattr(leave.employee, 'emp_id', None):
        from app.models.employee import Employee as PayrollEmployee
        payroll_emp = PayrollEmployee.objects.filter(employee_code__iexact=leave.employee.emp_id).first()
        if payroll_emp:
            try:
                leave.employee.payroll_employee = payroll_emp
                leave.employee.save(update_fields=['payroll_employee'])
            except Exception:
                pass

    return {
        'id': leave.id,
        'emp_id': leave.employee.emp_id if leave.employee else '',
        'employee_name': leave.employee.full_name if leave.employee else '',
        'employee_id': payroll_emp.id if payroll_emp else None,
        'request_type': leave.request_type,
        'start_date': str(leave.start_date),
        'end_date': str(leave.end_date),
        'duration_hours': leave.duration_hours,
        'reason': leave.reason,
        'status': leave.status,
        'admin_remarks': leave.admin_remarks or '',
        'created_at': leave.created_at.isoformat() if leave.created_at else '',
    }


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
            send_leave_request_notification_email(to_email=payroll.user.effective_notification_email, employee_name=payroll.full_name,
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


def _owner_attendance_q(request):
    """Q filter scoping an Attendance/LeaveRequest queryset (both FK'd via `employee`)
    to request.user's own company, matching the scoping LeaveActionView already uses."""
    effective_user = request.user
    is_admin = (
        bool(getattr(request.user, "is_platform_admin", False))
        or bool(getattr(request.user, "is_superuser", False))
        or bool(getattr(request.user, "is_staff", False))
        or str(getattr(request.user, "role", "")).strip().lower() in ("admin", "administrator")
    )
    if is_admin:
        target_id = (
            (request.query_params.get("company_user_id") if hasattr(request, "query_params") else None)
            or (request.GET.get("company_user_id") if hasattr(request, "GET") else None)
            or (request.headers.get("X-Company-User-Id") if hasattr(request, "headers") else None)
            or (request.headers.get("x-company-user-id") if hasattr(request, "headers") else None)
            or (request.headers.get("company-user-id") if hasattr(request, "headers") else None)
            or (request.META.get("HTTP_X_COMPANY_USER_ID") if hasattr(request, "META") else None)
            or (request.META.get("HTTP_COMPANY_USER_ID") if hasattr(request, "META") else None)
            or (request.data.get("company_user_id") if hasattr(request, "data") and isinstance(request.data, dict) else None)
        )
        if target_id is not None:
            clean_str = str(target_id).strip()
            if clean_str and clean_str.lower() not in ("null", "undefined", "none", "0", ""):
                from app.models.user import User
                try:
                    uid = int(clean_str)
                    target_user = User.objects.filter(id=uid).first()
                    if target_user:
                        effective_user = target_user
                    else:
                        return Q()
                except (ValueError, TypeError):
                    return Q()
            else:
                return Q()
        else:
            return Q()

    user_company = getattr(effective_user, 'company', None)
    user_emp_codes = list(effective_user.employees.values_list('employee_code', flat=True))
    q = (
        Q(employee__payroll_employee__user=effective_user) |
        Q(employee__payroll_employee__isnull=True, employee__emp_id__in=user_emp_codes)
    )
    if user_company:
        q |= Q(employee__payroll_employee__user__company=user_company)
    return q


class LeaveActionView(OwnerView):
    def get(self, request):
        q = _owner_attendance_q(request)
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

        if leave.employee and leave.employee.email:
            try:
                from app.services.email_service import send_leave_decision_email
                payroll_emp = getattr(leave.employee, 'payroll_employee', None)
                company_name = getattr(getattr(payroll_emp, 'user', None), 'company_name', '') if payroll_emp else ''
                send_leave_decision_email(
                    to_email=leave.employee.email,
                    employee_name=leave.employee.full_name,
                    request_type=leave.request_type,
                    start_date=str(leave.start_date),
                    end_date=str(leave.end_date),
                    status=leave.status,
                    admin_remarks=leave.admin_remarks or '',
                    company_name=company_name,
                )
            except Exception:
                import logging
                logging.getLogger(__name__).warning('Leave decision email delivery failed for request %s', leave.pk)
        return Response(leave_data(leave))


# Minutes to wait past an employee's checkout boundary before flagging a missed
# punch-out - without this, HR would get an email for every employee who simply
# taps out a few minutes after their shift end, which is normal, not a problem.
MISSED_CHECKOUT_GRACE_MINUTES = 20


class MissedCheckoutsView(OwnerView):
    """Lazily detects check-ins with no check-out past the employee's shift end
    (plus a grace period), one-time-notifies HR + the employee by email the first
    time each one is seen, and returns the still-open list for the notification
    dropdown. There's no cron in this project, so this is triggered by polling
    (the Header notification badge) rather than running on a schedule."""

    def get(self, request):
        q = _owner_attendance_q(request)
        now = timezone.localtime()
        open_records = Attendance.objects.select_related('employee__payroll_employee__user').filter(
            q, check_in__isnull=False, check_out__isnull=True,
        )

        flagged = []
        for record in open_records:
            payroll = record.employee.payroll_employee if record.employee else None
            if not payroll:
                continue
            company = getattr(payroll.user, 'company', None)
            cutoff, checkout_boundary = effective_shift_times(payroll, company)
            boundary_dt = timezone.make_aware(datetime.combine(record.date, checkout_boundary))
            if cutoff > checkout_boundary:  # night shift crosses midnight
                boundary_dt += timedelta(days=1)
            if now < boundary_dt + timedelta(minutes=MISSED_CHECKOUT_GRACE_MINUTES):
                continue

            flagged.append(record)
            if record.missed_checkout_notified_at:
                continue

            claimed = Attendance.objects.filter(pk=record.pk, missed_checkout_notified_at__isnull=True).update(
                missed_checkout_notified_at=now
            )
            if not claimed:
                continue  # another request already claimed/sent this one

            try:
                from app.services.email_service import send_missed_checkout_email, send_missed_checkout_reminder_email
                company_name = getattr(payroll.user, 'company_name', '') or ''
                check_in_str = format_punch_time(record.check_in)
                send_missed_checkout_email(
                    to_email=payroll.user.effective_notification_email,
                    employee_name=payroll.full_name,
                    date_str=str(record.date),
                    check_in=check_in_str,
                    company_name=company_name,
                )
                if record.employee.email:
                    send_missed_checkout_reminder_email(
                        to_email=record.employee.email,
                        employee_name=payroll.full_name,
                        date_str=str(record.date),
                        check_in=check_in_str,
                        company_name=company_name,
                    )
            except Exception:
                import logging
                logging.getLogger(__name__).warning('Missed-checkout email delivery failed for attendance %s', record.pk)

        return Response({'missed_checkouts': [
            {
                'id': r.pk,
                'employee_id': r.employee.payroll_employee_id if r.employee else None,
                'emp_id': r.employee.emp_id if r.employee else '',
                'employee_name': r.employee.full_name if r.employee else '',
                'date': str(r.date),
                'check_in': format_punch_time(r.check_in),
            }
            for r in flagged
        ]})


class UpdateAttendanceCheckoutView(OwnerView):
    """Lets HR fill in a check-out time an employee forgot to punch, correcting the
    record directly from the Attendance page."""

    def post(self, request):
        try:
            record_id = int(request.data.get('id', ''))
        except (ValueError, TypeError) as exc:
            raise ValidationError('Select a valid attendance record.') from exc

        checkout_str = str(request.data.get('check_out', '')).strip()
        match = re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d', checkout_str)
        if not match:
            raise ValidationError('Enter the check-out time in HH:MM (24-hour) format.')
        new_checkout = time(int(checkout_str[:2]), int(checkout_str[3:]))

        q = _owner_attendance_q(request)
        with transaction.atomic():
            # Postgres can't apply FOR UPDATE across the nullable payroll_employee
            # join that q's scoping filter uses, so check ownership first (no lock),
            # then lock by the bare pk only - same two-step pattern LeaveActionView
            # already uses for this exact reason.
            if not Attendance.objects.filter(q, pk=record_id).exists():
                raise PermissionDenied('Attendance record is unavailable.')
            # No select_related here: Postgres refuses FOR UPDATE across the nullable
            # payroll_employee join that select_related('employee__payroll_employee')
            # would pull in. employee/payroll are simple separate lookups below instead.
            record = Attendance.objects.select_for_update().filter(pk=record_id).first()
            if not record:
                raise PermissionDenied('Attendance record is unavailable.')
            if not record.check_in:
                raise ValidationError('This record has no check-in to pair a check-out with.')

            payroll = record.employee.payroll_employee if record.employee else None
            is_night_shift = False
            if payroll:
                company = getattr(payroll.user, 'company', None)
                cutoff, checkout_boundary = effective_shift_times(payroll, company)
                is_night_shift = cutoff > checkout_boundary
            if not is_night_shift and new_checkout <= record.check_in:
                raise ValidationError('Check-out time must be after check-in time.')

            record.check_out = new_checkout
            record.missed_checkout_notified_at = None
            record.save(update_fields=['check_out', 'missed_checkout_notified_at', 'updated_at'])

        return Response({'detail': 'Check-out time updated.', 'id': record.pk, 'check_out': format_punch_time(record.check_out)})


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
