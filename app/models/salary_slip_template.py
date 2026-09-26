from django.db import models
from django.conf import settings


class SalarySlipTemplate(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="salary_slip_templates",
        db_column="user_id"
    )
    template_name = models.CharField(max_length=255)
    template_html = models.TextField()
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "salary_slip_templates"

    def __str__(self):
        return self.template_name
