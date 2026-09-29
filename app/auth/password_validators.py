import re

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _


class StrongPasswordValidator:
    """Require a long password containing all major character groups."""

    def validate(self, password, user=None):
        errors = []
        if len(password) < 12:
            errors.append(_("Password must contain at least 12 characters."))
        if not re.search(r"[A-Z]", password):
            errors.append(_("Password must contain an uppercase letter."))
        if not re.search(r"[a-z]", password):
            errors.append(_("Password must contain a lowercase letter."))
        if not re.search(r"\d", password):
            errors.append(_("Password must contain a number."))
        if not re.search(r"[^A-Za-z0-9]", password):
            errors.append(_("Password must contain a special character."))

        if errors:
            raise ValidationError(errors, code="password_not_strong")

    def get_help_text(self):
        return _(
            "Use at least 12 characters with uppercase, lowercase, number, and special character."
        )
