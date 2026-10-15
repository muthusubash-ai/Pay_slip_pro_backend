"""Attendance identities are separate from payroll administrators."""
import hashlib
import secrets
import warnings
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from PIL import Image, ImageOps
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import (
    APIException,
    AuthenticationFailed,
    PermissionDenied,
    ValidationError,
)
from rest_framework.throttling import SimpleRateThrottle

from app.auth.authentication import JWTAuthentication

from .models import ActivationInvite, EmployeeSession

COOKIE = 'attendance_session'
COOKIE_PATH = '/api/attendance/'


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def issue_invite(employee):
    if not employee.is_active or not employee.user.is_active:
        raise ValidationError('Only active employees can be invited.')
    ActivationInvite.objects.filter(payroll_employee=employee, used=False).update(used=True)
    token = secrets.token_urlsafe(32)
    ActivationInvite.objects.create(payroll_employee=employee, email=employee.email.lower(), digest=digest(token), expires_at=timezone.now() + timedelta(hours=24))
    return token


def get_invite(request, lock=False):
    token = (
        request.headers.get('X-Attendance-Invite', '')
        or (getattr(request, 'query_params', None) and (request.query_params.get('invite') or request.query_params.get('token')))
        or (getattr(request, 'GET', None) and (request.GET.get('invite') or request.GET.get('token')))
        or (getattr(request, 'data', None) and isinstance(request.data, dict) and (request.data.get('invite') or request.data.get('token')))
        or ''
    )
    query = ActivationInvite.objects.select_for_update() if lock else ActivationInvite.objects
    invitation = query.filter(digest=digest(token), used=False, expires_at__gt=timezone.now()).first()
    if not invitation or not invitation.payroll_employee.is_active or not invitation.payroll_employee.user.is_active or invitation.email != invitation.payroll_employee.email.lower():
        raise PermissionDenied('A valid admin invitation is required. Ask your company administrator to send a new invitation.')
    return invitation


def check_password_strength(password, employee=None):
    if not isinstance(password, str) or len(password) > 256:
        raise ValidationError('Enter a password of at most 256 characters.')
    try:
        validate_password(password, user=employee)
    except DjangoValidationError as exc:
        raise ValidationError(' '.join(exc.messages)) from exc


def set_session(response, employee):
    EmployeeSession.objects.filter(expires_at__lte=timezone.now()).delete()
    token = secrets.token_urlsafe(32)
    EmployeeSession.objects.create(employee=employee, digest=digest(token), expires_at=timezone.now() + timedelta(hours=12))
    response.set_cookie(COOKIE, token, max_age=43200, httponly=True, secure=not settings.DEBUG, samesite=settings.AUTH_COOKIE_SAMESITE, path=COOKIE_PATH)
    response['Cache-Control'] = 'no-store'
    return response


class EmployeeAuthentication(BaseAuthentication):
    def authenticate_header(self, request):
        return 'Attendance'

    def authenticate(self, request):
        token = request.COOKIES.get(COOKIE)
        if not token:
            return None
        session = EmployeeSession.objects.select_related('employee__payroll_employee__user').filter(digest=digest(token), expires_at__gt=timezone.now()).first()
        if not session:
            raise AuthenticationFailed('Attendance session expired. Please sign in again.')
        employee = session.employee
        payroll = employee.payroll_employee
        if not employee.is_active or not payroll or not payroll.is_active or not payroll.user.is_active or employee.email.lower() != payroll.email.lower():
            raise AuthenticationFailed('Attendance account is inactive. Contact your administrator.')
        JWTAuthentication._enforce_csrf(request)
        return employee, session


class AttendanceThrottle(SimpleRateThrottle):
    scope = 'attendance'
    rate = '1000/hour' if settings.DEBUG else '120/hour'

    def get_cache_key(self, request, view):
        return self.cache_format % {'scope': self.scope, 'ident': self.get_ident(request)}


class LoginThrottle(AttendanceThrottle):
    scope = 'attendance_login'
    rate = '60/min' if settings.DEBUG else '20/min'


class PhotoThrottle(AttendanceThrottle):
    scope = 'attendance_photo'
    rate = '1000/hour' if settings.DEBUG else '20/hour'


class AccountLoginThrottle(AttendanceThrottle):
    scope = 'attendance_account_login'
    rate = '5/min'

    def get_cache_key(self, request, view):
        return self.cache_format % {'scope': self.scope, 'ident': digest(str(request.data.get('identifier', '')).strip().lower())}


class BiometricUnavailable(APIException):
    status_code = 503
    default_detail = 'Secure face verification is unavailable. Please contact your administrator.'


def encode_photo(upload):
    """Normalize and verify an image on the server. Never trust browser vectors."""
    if not upload or upload.size > settings.MAX_UPLOAD_SIZE:
        raise ValidationError('Upload a JPEG or PNG photo no larger than 5 MB.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            img = Image.open(upload)
            if img.format not in ('JPEG', 'PNG') or img.width * img.height > 16000000 or max(img.size) > 4096:
                raise ValueError('Invalid image')
            img.verify()
            upload.seek(0)
            img = ImageOps.exif_transpose(Image.open(upload)).convert('RGB')
            img.thumbnail((1280, 1280))
            img.load()
    except (OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValidationError('Invalid JPEG or PNG photo.') from exc
    try:
        import face_recognition
        import numpy as np
    except (ImportError, SystemExit) as exc:
        raise BiometricUnavailable() from exc
    array = np.array(img)
    locations = face_recognition.face_locations(array, model='hog')
    if len(locations) != 1:
        raise ValidationError('Use a clear photo containing exactly one face.')
    encodings = face_recognition.face_encodings(array, locations)
    if len(encodings) != 1:
        raise ValidationError('Unable to verify the face in this photo.')
    return [float(v) for v in encodings[0]]
