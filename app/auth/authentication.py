from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import BasePermission

from app.auth.jwt_handler import decode_token
from app.models.user import User, UserRole


class JWTAuthentication(BaseAuthentication):
    def authenticate(self, request):
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            return None

        parts = auth_header.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return None

        token = parts[1]
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

        return (user, token)


class IsAdmin(BasePermission):
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated and request.user.role == UserRole.admin


class IsAuthenticated(BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            from rest_framework.exceptions import NotAuthenticated
            raise NotAuthenticated("Not authenticated")
        return True
