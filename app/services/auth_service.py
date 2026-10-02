import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.cache import cache
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction

from app.auth.jwt_handler import (
    create_access_token,
    create_refresh_token,
    hash_password,
    token_digest,
    verify_password,
)
from app.exceptions import (
    BadRequestError,
    ConflictError,
    NotFoundError,
    UnauthorizedError,
)
from app.models.refresh_token import RefreshToken
from app.models.user import User

logger = logging.getLogger(__name__)

RESET_CODE_TTL_SECONDS = 15 * 60


def _reset_code_cache_key(email: str) -> str:
    email_digest = hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()
    return f"password-reset:{email_digest}"


def _reset_code_digest(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def register_user(db, email: str, password: str, full_name: str, phone: str = "") -> User:
    if User.objects.filter(email=email).exists():
        raise ConflictError("Email already registered")
    password_user = User(email=email, full_name=full_name)
    try:
        validate_password(password, user=password_user)
    except DjangoValidationError as exc:
        raise BadRequestError(" ".join(exc.messages))
    user = User(
        email=email,
        password=hash_password(password),
        full_name=full_name,
        phone=phone.strip() if phone else None,
    )
    user.save()
    logger.info("User registered: %s", email)
    return user


def authenticate_user(db, email: str, password: str) -> dict:
    clean_email = (email or "").strip().lower()
    try:
        user = User.objects.get(email__iexact=clean_email)
    except User.DoesNotExist:
        raise UnauthorizedError("Invalid email or password")

    if user.auth_provider == "google" and not user.password:
        raise UnauthorizedError("This account uses Google Sign-In. Please use the Google button to login.")
    
    if not verify_password(password, user.password):
        raise UnauthorizedError("Invalid email or password")
        
    if not user.is_active:
        raise UnauthorizedError("Account is deactivated")
        
    token_data = {"sub": str(user.id), "ver": user.auth_version}
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)
    
    db_token = RefreshToken(
        user=user,
        token=token_digest(refresh_token),
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )
    db_token.save()
    
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }


def refresh_tokens(db, refresh_token: str) -> dict:
    from app.auth.jwt_handler import decode_token

    payload = decode_token(refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise UnauthorizedError("Invalid refresh token")
        
    user_id = payload["sub"]
    digest = token_digest(refresh_token)
    replay_detected = False

    with transaction.atomic():
        try:
            db_token = RefreshToken.objects.select_for_update().select_related("user").get(
                token=digest
            )
        except RefreshToken.DoesNotExist:
            raise UnauthorizedError("Refresh token not found or revoked")

        if str(db_token.user_id) != str(user_id):
            raise UnauthorizedError("Invalid refresh token")
        if payload.get("ver", 0) != db_token.user.auth_version:
            raise UnauthorizedError("Session expired. Please sign in again.")
        if db_token.revoked:
            RefreshToken.objects.filter(user=db_token.user, revoked=False).update(revoked=True)
            replay_detected = True
        elif db_token.expires_at <= datetime.now(timezone.utc):
            db_token.revoked = True
            db_token.save(update_fields=["revoked"])
            raise UnauthorizedError("Refresh token has expired")
        else:
            user = db_token.user
            if not user.is_active:
                raise UnauthorizedError("User not found or inactive")

            db_token.revoked = True
            db_token.save(update_fields=["revoked"])
            token_data = {"sub": user_id, "ver": user.auth_version}
            new_access = create_access_token(token_data)
            new_refresh = create_refresh_token(token_data)
            RefreshToken.objects.create(
                user=user,
                token=token_digest(new_refresh),
                # Rotation must not extend the original session's maximum lifetime.
                expires_at=db_token.expires_at,
            )

    if replay_detected:
        raise UnauthorizedError("Refresh token reuse detected. Please sign in again.")
    
    return {
        "access_token": new_access,
        "refresh_token": new_refresh,
        "token_type": "bearer",
    }


def logout_user(db, refresh_token: str) -> None:
    try:
        db_token = RefreshToken.objects.get(token=token_digest(refresh_token))
        db_token.revoked = True
        db_token.save()
    except RefreshToken.DoesNotExist:
        pass


def update_profile(db, user: User, full_name: str | None = None, phone: str | None = None) -> User:
    if full_name is not None:
        user.full_name = full_name
    if phone is not None:
        user.phone = phone.strip() if phone else None
    user.save()
    return user


def generate_reset_code(db, email: str) -> str | None:
    """Generate a 6-digit reset code for the user email."""
    clean_email = (email or "").strip().lower()
    if not User.objects.filter(email__iexact=clean_email).exists():
        return None

    code = "".join(secrets.choice("0123456789") for _ in range(6))
    cache.set(
        _reset_code_cache_key(clean_email),
        _reset_code_digest(code),
        timeout=RESET_CODE_TTL_SECONDS,
    )
    logger.info("Reset code generated for %s", clean_email)
    return code


def reset_password_with_code(db, email: str, code: str, new_password: str) -> bool:
    """Reset web application login password using the emailed code.
    
    NOTE: This strictly resets the web application password (user.password).
    It NEVER touches user.admin_password so that Django Admin login
    credentials remain isolated and unaffected.
    """
    clean_email = (email or "").strip().lower()
    cache_key = _reset_code_cache_key(clean_email)
    stored_digest = cache.get(cache_key)
    if not stored_digest:
        raise BadRequestError("Reset code is missing or expired. Please request a new one.")
    if not secrets.compare_digest(stored_digest, _reset_code_digest(code)):
        raise BadRequestError("Invalid reset code.")

    with transaction.atomic():
        try:
            user = User.objects.select_for_update().get(email__iexact=clean_email)
        except User.DoesNotExist:
            raise NotFoundError("User") from None

        try:
            validate_password(new_password, user=user)
        except DjangoValidationError as exc:
            raise BadRequestError(" ".join(exc.messages)) from exc

        # Set ONLY web application login password
        user.set_password(new_password)
        if user.auth_provider == "google":
            user.auth_provider = "local"
        user.auth_version += 1
        user.save(update_fields=["password", "auth_provider", "auth_version", "updated_at"])
        RefreshToken.objects.filter(user=user, revoked=False).update(revoked=True)
    cache.delete(cache_key)
    logger.info("Password reset successful for %s", clean_email)
    return True
