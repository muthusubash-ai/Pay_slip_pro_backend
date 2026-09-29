import hashlib

from rest_framework.throttling import SimpleRateThrottle, UserRateThrottle


class IPRateThrottle(SimpleRateThrottle):
    def get_cache_key(self, request, view):
        return self.cache_format % {
            "scope": self.scope,
            "ident": self.get_ident(request),
        }


class AccountRateThrottle(SimpleRateThrottle):
    field_names = ("email", "username")

    def get_cache_key(self, request, view):
        identifier = ""
        for field_name in self.field_names:
            value = request.data.get(field_name)
            if value:
                identifier = str(value).strip().lower()
                break

        if not identifier:
            identifier = self.get_ident(request)

        digest = hashlib.sha256(identifier.encode("utf-8")).hexdigest()
        return self.cache_format % {
            "scope": self.scope,
            "ident": digest,
        }


class LoginIPRateThrottle(IPRateThrottle):
    scope = "login_ip"


class LoginAccountRateThrottle(AccountRateThrottle):
    scope = "login_account"


class PasswordResetRequestIPRateThrottle(IPRateThrottle):
    scope = "password_reset_request_ip"


class PasswordResetRequestAccountRateThrottle(AccountRateThrottle):
    scope = "password_reset_request_account"


class PasswordResetVerifyIPRateThrottle(IPRateThrottle):
    scope = "password_reset_verify_ip"


class PasswordResetVerifyAccountRateThrottle(AccountRateThrottle):
    scope = "password_reset_verify_account"


class LogoUploadRateThrottle(UserRateThrottle):
    scope = "logo_upload"

    def allow_request(self, request, view):
        if request.method != "POST":
            return True
        return super().allow_request(request, view)
