import re
from rest_framework import serializers
from app.models.employee import Employee


def _validate_employee_fields(data: dict):
    if "full_name" in data and data["full_name"]:
        val = str(data["full_name"]).strip()
        if not re.match(r"^[a-zA-Z\s.'-]+$", val):
            raise serializers.ValidationError({"full_name": "Full name must contain only letters and spaces."})
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
        ]

    def validate(self, attrs):
        _validate_employee_fields(attrs)
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
        ]
        extra_kwargs = {
            field: {"required": False, "allow_null": True}
            for field in fields
        }
        extra_kwargs["date_of_joining"] = {"required": False, "allow_null": False}

    def validate(self, attrs):
        _validate_employee_fields(attrs)
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
            "is_active",
        ]


class EmployeeListResponseSerializer(serializers.Serializer):
    items = EmployeeResponseSerializer(many=True)
    total = serializers.IntegerField()
    page = serializers.IntegerField()
    per_page = serializers.IntegerField()
    pages = serializers.IntegerField()
