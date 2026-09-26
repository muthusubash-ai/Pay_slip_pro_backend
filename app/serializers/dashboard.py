from rest_framework import serializers


class DashboardStatsSerializer(serializers.Serializer):
    total_employees = serializers.IntegerField()
    active_employees = serializers.IntegerField()
    total_payroll = serializers.FloatField()
    current_month_salary = serializers.FloatField()
    avg_salary = serializers.FloatField()


class PayrollSummarySerializer(serializers.Serializer):
    month = serializers.IntegerField()
    year = serializers.IntegerField()
    total_gross = serializers.FloatField()
    total_deductions = serializers.FloatField()
    total_net = serializers.FloatField()
    slip_count = serializers.IntegerField()


class DepartmentBreakdownSerializer(serializers.Serializer):
    department = serializers.CharField()
    employee_name = serializers.CharField()
    designation = serializers.CharField()
    employee_code = serializers.CharField()
    basic_salary = serializers.FloatField()
