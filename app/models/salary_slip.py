from django.db import models
from django.conf import settings
from app.models.employee import Employee


class SlipStatus:
    draft = "draft"
    generated = "generated"
    sent = "sent"

    CHOICES = [
        (draft, "draft"),
        (generated, "generated"),
        (sent, "sent"),
    ]


class SalarySlip(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="salary_slips",
        db_column="user_id"
    )
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="salary_slips",
        db_column="employee_id"
    )
    month = models.IntegerField()
    year = models.IntegerField()
    basic_salary = models.DecimalField(max_digits=12, decimal_places=2)
    hra = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    conveyance_allowance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    medical_allowance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    special_allowance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gross_salary = models.DecimalField(max_digits=12, decimal_places=2)
    pf_deduction = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    professional_tax = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tds = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    esi = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_deductions = models.DecimalField(max_digits=12, decimal_places=2)
    leave_days = models.IntegerField(default=0)
    leave_deduction = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    net_pay = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(
        max_length=20,
        choices=SlipStatus.CHOICES,
        default=SlipStatus.generated
    )
    generated_at = models.DateTimeField(auto_now_add=True)
    emailed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "salary_slips"
        unique_together = (("employee", "month", "year"),)

    def __str__(self):
        return f"Slip {self.employee.employee_code} - {self.month}/{self.year}"
