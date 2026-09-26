from django.db import models
from django.conf import settings
from app.models.employee import Employee


class AttendanceStatus:
    present = "present"
    leave = "leave"
    weekoff = "weekoff"

    CHOICES = [
        (present, "present"),
        (leave, "leave"),
        (weekoff, "weekoff"),
    ]


class Attendance(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        db_column="user_id"
    )
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        db_column="employee_id"
    )
    date = models.DateField()
    status = models.CharField(
        max_length=20,
        choices=AttendanceStatus.CHOICES,
        default=AttendanceStatus.present
    )

    class Meta:
        db_table = "attendance"
        unique_together = (("employee", "date"),)

    def __str__(self):
        return f"{self.employee.employee_code} - {self.date} - {self.status}"
