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


def parse_face_vector(stored):
    """Normalize a stored `Employee.face_encoding` value into a 128-float list, or None."""
    import json
    if not stored:
        return None
    if isinstance(stored, str):
        try:
            stored = json.loads(stored)
        except Exception:
            return None
    if isinstance(stored, dict):
        if 'descriptor' in stored:
            stored = stored['descriptor']
        elif 'face_encoding' in stored:
            stored = stored['face_encoding']
        elif 'face_descriptor' in stored:
            stored = stored['face_descriptor']
        else:
            try:
                stored = [stored[str(i)] for i in range(128)]
            except Exception:
                return None
    if isinstance(stored, (list, tuple)) and len(stored) == 128:
        try:
            return [float(x) for x in stored]
        except (ValueError, TypeError):
            return None
    return None


def face_distance(vector_a, vector_b):
    import math
    return math.dist(vector_a, vector_b)


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

    def parse_rate(self, rate):
        # Keep each subclass's configured request allowance, but always reset the
        # window every 30 seconds instead of the minute/hour window the rate string
        # implies - so a throttled action (face retake, face recognize, password
        # change, etc.) waits at most ~30s before it can be retried.
        num_requests, _ = super().parse_rate(rate)
        return num_requests, 30

    def get_cache_key(self, request, view):
        return self.cache_format % {'scope': self.scope, 'ident': self.get_ident(request)}


class LoginThrottle(AttendanceThrottle):
    scope = 'attendance_login'
    # Numerator is the cap for the 30s window (see parse_rate above) - 10 keeps the
    # same effective per-minute ceiling as the original 20/min, just with a shorter,
    # friendlier wait once throttled, instead of silently doubling the brute-force
    # allowance that a plain window-shrink would have caused.
    rate = '60/min' if settings.DEBUG else '10/min'


class PhotoThrottle(AttendanceThrottle):
    scope = 'attendance_photo'
    # This gates face capture on EmployeeRegisterView (public, unauthenticated) and
    # the face-encoding checks on VerifyFaceView/MarkAttendanceView, which are all
    # CPU-expensive. Numerator is the cap for the 30s window (see parse_rate above):
    # 6 is enough for a few legitimate retakes, without opening the public register
    # endpoint up to the ~2400/hour a naive window-shrink from 20/hour would allow.
    rate = '1000/hour' if settings.DEBUG else '6/hour'


class AccountLoginThrottle(AttendanceThrottle):
    scope = 'attendance_account_login'
    # Numerator is the cap for the 30s window (see parse_rate above) - kept at the
    # original 5 wrong-attempts-before-block ceiling per account; only the window
    # is shorter now (30s instead of 60s), so the block itself clears faster.
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
        import logging
        logging.getLogger(__name__).exception("Secure face verification dependency error: %s", exc)
        raise BiometricUnavailable() from exc
    array = np.array(img)
    locations = face_recognition.face_locations(array, number_of_times_to_upsample=1, model='hog')
    if len(locations) == 0:
        # Retry with upsampling to catch smaller or distant webcam faces
        locations = face_recognition.face_locations(array, number_of_times_to_upsample=2, model='hog')
    if len(locations) == 0:
        # Fallback to OpenCV CascadeClassifier if available
        try:
            import cv2
            gray = cv2.cvtColor(array, cv2.COLOR_RGB2GRAY)
            cascades = []
            if hasattr(cv2, 'CascadeClassifier') and hasattr(cv2, 'data'):
                for xml_name in ['haarcascade_frontalface_default.xml', 'haarcascade_frontalface_alt2.xml']:
                    try:
                        c = cv2.CascadeClassifier(cv2.data.haarcascades + xml_name)
                        if not c.empty():
                            cascades.append(c)
                    except Exception:
                        pass
            for cascade in cascades:
                detected = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=3, minSize=(30, 30))
                if len(detected) > 0:
                    locations = [(int(y), int(x + w), int(y + h), int(x)) for (x, y, w, h) in detected]
                    break
        except Exception:
            pass

    if len(locations) == 0:
        raise ValidationError('No clear human face detected. Please face the camera and try again.')

    if len(locations) > 1:
        # In selfie / kiosk capture, pick the largest foreground face
        locations = sorted(locations, key=lambda loc: (loc[2] - loc[0]) * (loc[1] - loc[3]), reverse=True)
        primary_face = locations[0]
        locations = [primary_face]

    encodings = face_recognition.face_encodings(array, locations)
    if len(encodings) != 1:
        raise ValidationError('Unable to verify the face in this photo.')
    return [float(v) for v in encodings[0]]
