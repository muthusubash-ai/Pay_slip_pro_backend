from django.conf import settings


def set_auth_cookies(response, tokens: dict) -> None:
    common = {
        "httponly": True,
        "secure": settings.AUTH_COOKIE_SECURE,
        "samesite": settings.AUTH_COOKIE_SAMESITE,
        "domain": settings.AUTH_COOKIE_DOMAIN,
    }
    response.set_cookie(
        settings.AUTH_ACCESS_COOKIE_NAME,
        tokens["access_token"],
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/api/",
        **common,
    )
    response.set_cookie(
        settings.AUTH_REFRESH_COOKIE_NAME,
        tokens["refresh_token"],
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        path="/api/v1/auth/",
        **common,
    )


def clear_auth_cookies(response) -> None:
    common = {
        "domain": settings.AUTH_COOKIE_DOMAIN,
        "samesite": settings.AUTH_COOKIE_SAMESITE,
    }
    response.delete_cookie(settings.AUTH_ACCESS_COOKIE_NAME, path="/api/", **common)
    response.delete_cookie(
        settings.AUTH_REFRESH_COOKIE_NAME,
        path="/api/v1/auth/",
        **common,
    )
