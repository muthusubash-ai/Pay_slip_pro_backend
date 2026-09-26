from django.db import models
from django.conf import settings
from app.models.base import TimestampModel


class Company(TimestampModel):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="company",
        db_column="user_id"
    )
    company_name = models.CharField(max_length=255)
    logo_url = models.CharField(max_length=500, null=True, blank=True)
    logo_data = models.TextField(null=True, blank=True)  # Base64-encoded logo image
    primary_color = models.CharField(max_length=7, default="#000000", null=True, blank=True)  # Hex color
    address = models.TextField(null=True, blank=True)
    city = models.CharField(max_length=100, null=True, blank=True)
    state = models.CharField(max_length=100, null=True, blank=True)
    zip_code = models.CharField(max_length=20, null=True, blank=True)
    pay_day = models.IntegerField(default=1)
    financial_year_start = models.IntegerField(default=4)
    pf_number = models.CharField(max_length=50, null=True, blank=True)
    tan_number = models.CharField(max_length=50, null=True, blank=True)

    class Meta:
        db_table = "companies"

    def __str__(self):
        return self.company_name
