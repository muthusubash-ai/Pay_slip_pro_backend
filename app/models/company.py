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
    office_lat = models.FloatField(default=8.7892563, null=True, blank=True)
    office_lng = models.FloatField(default=78.117146, null=True, blank=True)
    allowed_radius_meters = models.IntegerField(default=70, null=True, blank=True)
    # Recurring weekly off days for this company, e.g. [6] for Sunday-only or [5, 6] for Sat+Sun.
    # Uses Python's date.weekday() convention: Monday=0 ... Sunday=6.
    weekly_off_days = models.JSONField(default=list, blank=True)
    # Permission requests allowed per month with 0 salary deduction. Any permission beyond
    # this count in the same month deducts 1 full day each.
    permission_days_per_month = models.IntegerField(default=3)
    # Office work timings and check-in/out schedules
    office_timing = models.CharField(max_length=100, default="09:30 AM - 06:00 PM", null=True, blank=True)
    office_start_time = models.CharField(max_length=20, default="09:30", null=True, blank=True)
    office_end_time = models.CharField(max_length=20, default="18:00", null=True, blank=True)
    # Optional feature: when enabled, HR can set a per-employee shift start/end time
    # (Employee.shift_start_time/shift_end_time) that overrides the company-wide
    # office timing above for that employee's attendance late-cutoff/checkout.
    enable_employee_shift_timing = models.BooleanField(default=False)

    class Meta:
        db_table = "companies"

    def __str__(self):
        return self.company_name
