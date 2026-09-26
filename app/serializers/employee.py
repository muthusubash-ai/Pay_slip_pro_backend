from rest_framework import serializers
from app.models.employee import Employee


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


class EmployeeUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Employee
        fields = [
            "full_name",
            "email",
            "phone",
            "department",
            "designation",
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
