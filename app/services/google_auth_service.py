import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from django.conf import settings

from app.auth.jwt_handler import create_access_token, create_refresh_token
from app.exceptions import BadRequestError, UnauthorizedError
from app.models.refresh_token import RefreshToken
from app.models.user import User

logger = logging.getLogger(__name__)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"


def get_google_login_url() -> str:
    """Generate the Google OAuth consent screen URL."""
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "consent",
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


async def exchange_code_for_tokens(code: str) -> dict:
    """Exchange the authorization code for Google tokens."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "redirect_uri": settings.GOOGLE_REDIRECT_URI,
                "grant_type": "authorization_code",
            },
        )
        if response.status_code != 200:
            logger.error("Google token exchange failed: %s", response.text)
            raise BadRequestError("Failed to authenticate with Google")
        return response.json()


async def get_google_user_info(access_token: str) -> dict:
    """Fetch user info from Google using the access token."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if response.status_code != 200:
            logger.error("Google userinfo failed: %s", response.text)
            raise BadRequestError("Failed to get user info from Google")
        return response.json()


def get_or_create_google_user(db, google_user: dict) -> User:
    """Find existing user by google_id or email, or create a new one."""
    google_id = str(google_user["id"])
    email = google_user["email"]
    full_name = google_user.get("name", email.split("@")[0])

    # Check by google_id first
    user = User.objects.filter(google_id=google_id).first()
    if user:
        return user

    # Check by email (link existing account)
    user = User.objects.filter(email=email).first()
    if user:
        user.google_id = google_id
        user.auth_provider = "google"
        user.save()
        logger.info("Linked Google account to existing user: %s", email)
        return user

    # Create new user
    user = User(
        email=email,
        full_name=full_name,
        google_id=google_id,
        auth_provider="google",
        password=None,
    )
    user.save()
    logger.info("Created new Google user: %s", email)
    return user


def generate_tokens_for_user(db, user: User) -> dict:
    """Generate JWT access and refresh tokens for a user."""
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
