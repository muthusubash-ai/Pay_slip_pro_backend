from django.db import models
from django.utils import timezone


class Employee(models.Model):
    emp_id = models.CharField(max_length=20, db_index=True)
    payroll_employee = models.OneToOneField('app.Employee', null=True, blank=True, on_delete=models.CASCADE, related_name='attendance_account')
    google_subject = models.CharField(max_length=255, blank=True, default='')
    full_name = models.CharField(max_length=150)
    email = models.EmailField(unique=True)
    password = models.CharField(max_length=256, null=True, blank=True)
    designation = models.CharField(max_length=100, default='Employee')
    joining_date = models.DateField(null=True, blank=True)
    phone_number = models.CharField(max_length=20, null=True, blank=True)
    face_encoding = models.JSONField(help_text="128-dimensional face embedding vector or pixel signature", null=True, blank=True)
    profile_photo = models.ImageField(upload_to="employees/photos/", null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)




    def set_password(self, raw_password):
        from django.contrib.auth.hashers import make_password
        if raw_password:
            self.password = make_password(raw_password)

    @property
    def is_authenticated(self):
        return True

    def check_password(self, raw_password):
        from django.contrib.auth.hashers import check_password
        if not raw_password:
            return False
        
        # If user account was created before password was required (password is None or empty)
        if not self.password:
            return False

        # Check standard Django hashed password
        if self.password.startswith(('pbkdf2_sha256$', 'pbkdf2_', 'argon2', 'bcrypt')):
            return check_password(raw_password, self.password)

        return False

    def __str__(self):
        return f"{self.emp_id} - {self.full_name}"

class ActivationInvite(models.Model):
    payroll_employee = models.ForeignKey('app.Employee', on_delete=models.CASCADE)
    digest = models.CharField(max_length=64, unique=True)
    email = models.EmailField()
    expires_at = models.DateTimeField()
    used = models.BooleanField(default=False)


class EmployeeSession(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE)
    digest = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()


class Attendance(models.Model):
    STATUS_CHOICES = (
        ('PRESENT', 'On Time (Present)'),
        ('LATE', 'Late Arrival'),
        ('HALF_DAY', 'Half Day'),
        ('ABSENT', 'Absent'),
    )
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='attendances')
    date = models.DateField(auto_now_add=True, db_index=True)
    check_in = models.TimeField(null=True, blank=True)
    check_out = models.TimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PRESENT')
    punch_latitude = models.FloatField()
    punch_longitude = models.FloatField()
    distance_meters = models.FloatField()
    verification_photo = models.ImageField(upload_to="attendance/punches/%Y/%m/%d/", null=True, blank=True)
    # Set once a "missed punch-out" HR notification + email has been sent for this
    # record, so the lazy detection check (no cron in this project) never sends it
    # twice. Cleared implicitly once check_out is filled in (no further checks match).
    missed_checkout_notified_at = models.DateTimeField(null=True, blank=True)
    # A temporary step-out during the day under an APPROVED permission request (e.g.
    # "2 hour permission") - the employee punches out at permission_out, then punches
    # back in at permission_in once their permission time is up, and the day's single
    # check_in/check_out continue to bound the whole day as before.
    permission_out = models.TimeField(null=True, blank=True)
    permission_in = models.TimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)



    class Meta:
        unique_together = ('employee', 'date')
        ordering = ['-date', '-check_in']

    def __str__(self):
        return f"{self.employee.emp_id} - {self.date} ({self.status})"

class LeaveRequest(models.Model):
    TYPE_CHOICES = (
        ('SICK', 'Sick Leave'),
        ('CASUAL', 'Casual Leave'),
        ('HALF_DAY', 'Half Day Leave'),
        ('PERMISSION', 'Permission Request'),
    )
    STATUS_CHOICES = (
        ('PENDING', 'Pending'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
    )

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='leave_requests')
    request_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='CASUAL')
    start_date = models.DateField()
    end_date = models.DateField()
    duration_hours = models.FloatField(null=True, blank=True, help_text="Hours requested for PERMISSION type")
    reason = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    admin_remarks = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.employee.emp_id} - {self.request_type} ({self.status})"
