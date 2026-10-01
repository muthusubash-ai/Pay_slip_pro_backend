from django.conf import settings
from django.middleware.csrf import CsrfViewMiddleware
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied
from rest_framework.permissions import BasePermission

from app.auth.jwt_handler import decode_token
from app.models.user import User


class JWTAuthentication(BaseAuthentication):
    def authenticate(self, request):
        auth_header = request.headers.get("Authorization")
        cookie_authenticated = False
        if auth_header:
            parts = auth_header.split()
            if len(parts) != 2 or parts[0].lower() != "bearer":
                return None
            token = parts[1]
        else:
            token = request.COOKIES.get(settings.AUTH_ACCESS_COOKIE_NAME)
            if not token:
                return None
            cookie_authenticated = True
        payload = decode_token(token)
        if not payload or payload.get("type") != "access":
            raise AuthenticationFailed("Invalid token")

        user_id = payload.get("sub")
        if not user_id:
            raise AuthenticationFailed("Invalid token")

        try:
            user = User.objects.get(id=int(user_id))
        except (User.DoesNotExist, ValueError):
            raise AuthenticationFailed("User not found or inactive")

        if not user.is_active:
            raise AuthenticationFailed("User not found or inactive")
        if payload.get("ver", 0) != user.auth_version:
            raise AuthenticationFailed("Session expired. Please sign in again.")

        if cookie_authenticated:
            self._enforce_csrf(request)

        return (user, token)

    @staticmethod
    def _enforce_csrf(request):
        check = CsrfViewMiddleware(lambda req: None)
        check.process_request(request)
        reason = check.process_view(request, None, (), {})
        if reason:
            raise PermissionDenied(f"CSRF validation failed: {reason}")


class IsAdmin(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_platform_admin)


class IsAuthenticated(BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            from rest_framework.exceptions import NotAuthenticated
            raise NotAuthenticated("Not authenticated")
        return True
