from rest_framework import serializers
from app.models.salary_slip import SalarySlip
from app.serializers.employee import EmployeeResponseSerializer


class GenerateSlipsRequestSerializer(serializers.Serializer):
    month = serializers.IntegerField()
    year = serializers.IntegerField()


class SalarySlipResponseSerializer(serializers.ModelSerializer):
    employee = EmployeeResponseSerializer(required=False, read_only=True)
    leave_days = serializers.SerializerMethodField()
    leave_deduction = serializers.SerializerMethodField()

    class Meta:
        model = SalarySlip
        fields = [
            "id",
            "employee_id",
            "month",
            "year",
            "basic_salary",
            "hra",
            "conveyance_allowance",
            "medical_allowance",
            "special_allowance",
            "gross_salary",
            "pf_deduction",
            "professional_tax",
            "tds",
            "esi",
            "total_deductions",
            "leave_days",
            "leave_deduction",
            "net_pay",
            "status",
            "generated_at",
            "emailed_at",
            "employee",
        ]

    def get_leave_days(self, obj):
        return obj.leave_days if obj.leave_days is not None else 0

    def get_leave_deduction(self, obj):
        return float(obj.leave_deduction) if obj.leave_deduction is not None else 0.0


class SalarySlipListResponseSerializer(serializers.Serializer):
    items = SalarySlipResponseSerializer(many=True)
    total = serializers.IntegerField()
    page = serializers.IntegerField()
    per_page = serializers.IntegerField()
    pages = serializers.IntegerField()
