from django.contrib.auth.backends import ModelBackend
from app.models.user import User


class DjangoAdminAuthBackend(ModelBackend):
    """
    Dedicated authentication backend for Django Admin (/admin/).
    Validates credentials against user.admin_password so that
    Django Admin credentials are completely separate from the
    web application (/login) credentials.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            username = kwargs.get(User.USERNAME_FIELD)
        if not username or not password:
            return None

        clean_email = str(username).strip().lower()
        try:
            user = User.objects.get(email__iexact=clean_email)
        except User.DoesNotExist:
            return None

        # Only active staff / platform admin users can authenticate in Django Admin
        if not user.is_active or not (user.is_staff or user.is_platform_admin):
            return None

        # Check against admin_password (with fallback if admin_password not set)
        if user.check_admin_password(password):
            return user

        return None
