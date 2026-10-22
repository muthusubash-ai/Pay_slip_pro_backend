import re
from rest_framework import serializers
from app.models.employee import Employee


def _validate_employee_fields(data: dict, user=None, instance=None):
    if "full_name" in data and data["full_name"]:
        val = str(data["full_name"]).strip()
        if not re.match(r"^[a-zA-Z\s.'-]+$", val):
            raise serializers.ValidationError({"full_name": "Full name must contain only letters and spaces."})
    if "email" in data and data["email"]:
        email_val = str(data["email"]).strip().lower()
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email_val):
            raise serializers.ValidationError({"email": "Enter a valid email address."})

        # Check against existing active employees
        qs = Employee.objects.filter(email__iexact=email_val, is_active=True)
        if user:
            qs = qs.filter(user=user)
        if instance:
            qs = qs.exclude(pk=instance.pk)

        conflict_emp = qs.first()
        if conflict_emp:
            raise serializers.ValidationError({
                "email": f"This email is already assigned to employee {conflict_emp.employee_code} ({conflict_emp.full_name}). Each employee must have a unique email address."
            })

        # Check against existing active attendance accounts
        try:
            from attendance.models import Employee as AttendanceEmployee
            att_emp = AttendanceEmployee.objects.filter(email__iexact=email_val, is_active=True).first()
            if att_emp:
                current_code = data.get("employee_code") or (instance.employee_code if instance else None)
                if att_emp.payroll_employee_id and instance and att_emp.payroll_employee_id != instance.pk:
                    raise serializers.ValidationError({
                        "email": f"This email is already assigned to another attendance account ({att_emp.emp_id} - {att_emp.full_name}). Each employee must have a unique email address."
                    })
                elif att_emp.payroll_employee_id and not instance:
                    raise serializers.ValidationError({
                        "email": f"This email is already assigned to another attendance account ({att_emp.emp_id} - {att_emp.full_name}). Each employee must have a unique email address."
                    })
                elif current_code and att_emp.emp_id and att_emp.emp_id.lower() != str(current_code).lower():
                    raise serializers.ValidationError({
                        "email": f"This email is already assigned to another attendance account ({att_emp.emp_id} - {att_emp.full_name}). Each employee must have a unique email address."
                    })
        except serializers.ValidationError:
            raise
        except Exception:
            pass
    if "bank_name" in data and data["bank_name"]:
        val = str(data["bank_name"]).strip()
        if not re.fullmatch(r"[a-zA-Z0-9\s.&'()-]+", val):
            raise serializers.ValidationError({"bank_name": "Bank name contains unsupported characters."})
    if "phone" in data and data["phone"]:
        val = str(data["phone"]).strip()
        if not re.match(r"^\+?[0-9]{10,15}$", val):
            raise serializers.ValidationError({"phone": "Phone number must contain only 10-15 digits."})
    if "bank_account_number" in data and data["bank_account_number"]:
        val = str(data["bank_account_number"]).strip()
        if not re.match(r"^\d{6,20}$", val):
            raise serializers.ValidationError({"bank_account_number": "Bank account number must contain only 6-20 digits."})
    for field in ("shift_start_time", "shift_end_time"):
        if field in data and data[field]:
            val = str(data[field]).strip()
            if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", val):
                raise serializers.ValidationError({field: "Enter a valid 24-hour time in HH:MM format (e.g. 09:30)."})


class EmployeeCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Employee
        fields = [
            "employee_code",
            "full_name",
            "email",
            "phone",
            "department",
            "designation",
            "date_of_joining",
            "bank_account_number",
            "bank_name",
            "ifsc_code",
            "pan_number",
            "basic_salary",
            "hra",
            "conveyance_allowance",
            "medical_allowance",
            "special_allowance",
            "pf_deduction",
            "professional_tax",
            "tds",
            "esi",
            "shift_start_time",
            "shift_end_time",
            "gender",
        ]

    def validate(self, attrs):
        request = self.context.get("request")
        user = getattr(request, "user", None) if request else None
        _validate_employee_fields(attrs, user=user)
        return attrs


class EmployeeUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Employee
        fields = [
            "full_name",
            "email",
            "phone",
            "department",
            "designation",
            "date_of_joining",
            "bank_account_number",
            "bank_name",
            "ifsc_code",
            "pan_number",
            "basic_salary",
            "hra",
            "conveyance_allowance",
            "medical_allowance",
            "special_allowance",
            "pf_deduction",
            "professional_tax",
            "tds",
            "esi",
            "shift_start_time",
            "shift_end_time",
            "gender",
        ]
        extra_kwargs = {
            field: {"required": False, "allow_null": True}
            for field in fields
        }
        extra_kwargs["date_of_joining"] = {"required": False, "allow_null": False}

    def validate(self, attrs):
        request = self.context.get("request")
        user = getattr(request, "user", None) if request else None
        _validate_employee_fields(attrs, user=user, instance=self.instance)
        return attrs


class EmployeeResponseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Employee
        fields = [
            "id",
            "employee_code",
            "full_name",
            "email",
            "phone",
            "department",
            "designation",
            "date_of_joining",
            "bank_account_number",
            "bank_name",
            "ifsc_code",
            "pan_number",
            "basic_salary",
            "hra",
            "conveyance_allowance",
            "medical_allowance",
            "special_allowance",
            "pf_deduction",
            "professional_tax",
            "tds",
            "esi",
            "shift_start_time",
            "shift_end_time",
            "gender",
            "is_active",
            "deactivated_at",
            "created_at",
            "updated_at",
        ]


class EmployeeListResponseSerializer(serializers.Serializer):
    items = EmployeeResponseSerializer(many=True)
    total = serializers.IntegerField()
    page = serializers.IntegerField()
    per_page = serializers.IntegerField()
    pages = serializers.IntegerField()
    active_count = serializers.IntegerField(required=False, default=0)
    inactive_count = serializers.IntegerField(required=False, default=0)
