import base64
import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from django.conf import settings
from django.core.cache import cache

from app.auth.jwt_handler import create_access_token, create_refresh_token, token_digest
from app.exceptions import BadRequestError, UnauthorizedError
from app.models.refresh_token import RefreshToken
from app.models.user import User

logger = logging.getLogger(__name__)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"


def _oauth_state_cache_key(state: str) -> str:
    digest = hashlib.sha256(state.encode("utf-8")).hexdigest()
    return f"google-oauth-state:{digest}"


def create_google_login_request() -> tuple[str, str]:
    """Create a one-time state-bound Google authorization request with PKCE."""
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        raise BadRequestError("Google sign-in is not configured")

    state = secrets.token_urlsafe(32)
    code_verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")
    cache.set(
        _oauth_state_cache_key(state),
        code_verifier,
        timeout=settings.GOOGLE_OAUTH_STATE_TTL_SECONDS,
    )

    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "access_type": "online",
        "prompt": "select_account",
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}", state


def consume_google_oauth_state(state: str, cookie_state: str) -> str:
    """Validate browser binding and consume the state exactly once."""
    if not state or not cookie_state or not secrets.compare_digest(state, cookie_state):
        raise BadRequestError("Invalid OAuth state")

    cache_key = _oauth_state_cache_key(state)
    code_verifier = cache.get(cache_key)
    cache.delete(cache_key)
    if not code_verifier:
        raise BadRequestError("OAuth state is invalid or expired")
    return code_verifier


async def exchange_code_for_tokens(code: str, code_verifier: str) -> dict:
    """Exchange the authorization code for Google tokens."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": settings.GOOGLE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_CLIENT_SECRET,
                    "redirect_uri": settings.GOOGLE_REDIRECT_URI,
                    "grant_type": "authorization_code",
                    "code_verifier": code_verifier,
                },
                timeout=10.0,
            )
    except httpx.HTTPError:
        logger.warning("Google token exchange request failed")
        raise BadRequestError("Failed to authenticate with Google")

    if response.status_code != 200:
        logger.warning("Google token exchange failed with status %d", response.status_code)
        raise BadRequestError("Failed to authenticate with Google")
    token_data = response.json()
    if not token_data.get("access_token"):
        raise BadRequestError("Google did not return a valid access token")
    return token_data


async def get_google_user_info(access_token: str) -> dict:
    """Fetch user info from Google using the access token."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=10.0,
            )
    except httpx.HTTPError:
        logger.warning("Google userinfo request failed")
        raise BadRequestError("Failed to get user info from Google")

    if response.status_code != 200:
        logger.warning("Google userinfo failed with status %d", response.status_code)
        raise BadRequestError("Failed to get user info from Google")
    return response.json()


def get_or_create_google_user(db, google_user: dict) -> User:
    """Find existing user by google_id or email, or create a new one."""
    if google_user.get("verified_email") is not True:
        raise UnauthorizedError("Google account email is not verified")

    google_id = str(google_user.get("id", "")).strip()
    email = str(google_user.get("email", "")).strip().lower()
    if not google_id or not email:
        raise UnauthorizedError("Google account identity is incomplete")
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
        token=token_digest(refresh_token),
        expires_at=datetime.now(timezone.utc)
        + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )
    db_token.save()

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }
