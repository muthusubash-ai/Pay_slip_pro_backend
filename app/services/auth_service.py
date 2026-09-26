import logging
import random
import string
from datetime import datetime, timedelta, timezone

from app.auth.jwt_handler import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
)
from app.exceptions import BadRequestError, ConflictError, NotFoundError, UnauthorizedError
from app.models.refresh_token import RefreshToken
from app.models.user import User

logger = logging.getLogger(__name__)

# In-memory store for reset codes: {email: {"code": str, "expires": datetime}}
_reset_codes: dict[str, dict] = {}


def register_user(db, email: str, password: str, full_name: str) -> User:
    if User.objects.filter(email=email).exists():
        raise ConflictError("Email already registered")
    user = User(
        email=email, password=hash_password(password), full_name=full_name
    )
    user.save()
    logger.info("User registered: %s", email)
    return user


def authenticate_user(db, email: str, password: str) -> dict:
    try:
        user = User.objects.get(email=email)
    except User.DoesNotExist:
        raise UnauthorizedError("Invalid email or password")

    if user.auth_provider == "google" and not user.password:
        raise UnauthorizedError("This account uses Google Sign-In. Please use the Google button to login.")
    
    if not verify_password(password, user.password):
        raise UnauthorizedError("Invalid email or password")
        
    if not user.is_active:
        raise UnauthorizedError("Account is deactivated")
        
    access_token = create_access_token({"sub": str(user.id)})
    refresh_token = create_refresh_token({"sub": str(user.id)})
    
    db_token = RefreshToken(
        user=user,
        token=refresh_token,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
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
        
    try:
        db_token = RefreshToken.objects.get(token=refresh_token, revoked=False)
    except RefreshToken.DoesNotExist:
        raise UnauthorizedError("Refresh token not found or revoked")
        
    db_token.revoked = True
    db_token.save()
    
    user_id = payload["sub"]
    try:
        user = User.objects.get(id=int(user_id))
    except User.DoesNotExist:
        raise UnauthorizedError("User not found")
        
    new_access = create_access_token({"sub": user_id})
    new_refresh = create_refresh_token({"sub": user_id})
    
    new_db_token = RefreshToken(
        user=user,
        token=new_refresh,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    new_db_token.save()
    
    return {
        "access_token": new_access,
        "refresh_token": new_refresh,
        "token_type": "bearer",
    }


def logout_user(db, refresh_token: str) -> None:
    try:
        db_token = RefreshToken.objects.get(token=refresh_token)
        db_token.revoked = True
        db_token.save()
    except RefreshToken.DoesNotExist:
        pass


def update_profile(db, user: User, full_name: str | None, role: str | None = None) -> User:
    if full_name is not None:
        user.full_name = full_name
    if role is not None:
        user.role = role
    user.save()
    return user


def generate_reset_code(db, email: str) -> str | None:
    """Generate a 6-digit reset code for the user email."""
    if not User.objects.filter(email=email).exists():
        return None

    code = "".join(random.choices(string.digits, k=6))
    _reset_codes[email.lower()] = {
        "code": code,
        "expires": datetime.now(timezone.utc) + timedelta(minutes=15),
    }
    logger.info("Reset code generated for %s", email)
    return code


def reset_password_with_code(db, email: str, code: str, new_password: str) -> bool:
    """Reset password using the emailed code."""
    email_lower = email.lower()
    stored = _reset_codes.get(email_lower)
    if not stored:
        raise BadRequestError("No reset code found. Please request a new one.")
    if datetime.now(timezone.utc) > stored["expires"]:
        _reset_codes.pop(email_lower, None)
        raise BadRequestError("Reset code has expired. Please request a new one.")
    if stored["code"] != code:
        raise BadRequestError("Invalid reset code.")

    try:
        user = User.objects.get(email=email)
    except User.DoesNotExist:
        raise NotFoundError("User")

    user.password = hash_password(new_password)
    user.save()
    _reset_codes.pop(email_lower, None)
    logger.info("Password reset successful for %s", email)
    return True
