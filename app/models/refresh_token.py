from django.db import models
from django.conf import settings


class RefreshToken(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="refresh_tokens",
        db_column="user_id"
    )
    token = models.CharField(max_length=500, unique=True, db_index=True)
    expires_at = models.DateTimeField()
    revoked = models.BooleanField(default=False)

    class Meta:
        db_table = "refresh_tokens"

    def __str__(self):
        return f"Token for {self.user.email}"
