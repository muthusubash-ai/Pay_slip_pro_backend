from rest_framework import serializers
from app.models.attendance import Attendance


class AttendanceCreateSerializer(serializers.Serializer):
    employee_id = serializers.IntegerField()
    date = serializers.DateField()
    status = serializers.CharField()


class AttendanceBulkCreateSerializer(serializers.Serializer):
    employee_id = serializers.IntegerField()
    month = serializers.IntegerField(min_value=1, max_value=12)
    year = serializers.IntegerField(min_value=1900, max_value=2100)
    leave_dates = serializers.ListField(child=serializers.DateField())
    half_day_dates = serializers.ListField(child=serializers.DateField(), required=False, default=[])
    permission_dates = serializers.ListField(child=serializers.DateField(), required=False, default=[])

    def validate(self, attrs):
        date_fields = ("leave_dates", "half_day_dates", "permission_dates")
        selected = [day for field in date_fields for day in attrs.get(field, [])]
        if any(day.month != attrs["month"] or day.year != attrs["year"] for day in selected):
            raise serializers.ValidationError("Attendance dates must be in the selected month and year.")
        if len(selected) != len(set(selected)):
            raise serializers.ValidationError("An attendance date can only have one status.")
        return attrs


class AttendanceResponseSerializer(serializers.Serializer):
    id = serializers.IntegerField(required=False, allow_null=True)
    employee_id = serializers.IntegerField()
    date = serializers.DateField()
    status = serializers.CharField()
    check_in = serializers.CharField(required=False, allow_null=True)
    check_out = serializers.CharField(required=False, allow_null=True)
    duration_hours = serializers.FloatField(required=False, allow_null=True)
    is_late = serializers.BooleanField(required=False, default=False)
    bio_record_id = serializers.IntegerField(required=False, allow_null=True)
    permission_out = serializers.CharField(required=False, allow_null=True)
    permission_in = serializers.CharField(required=False, allow_null=True)
    biometric_status = serializers.CharField(required=False, allow_null=True)
    leave_type = serializers.CharField(required=False, allow_null=True)
    distance_meters = serializers.FloatField(required=False, allow_null=True)


class EmployeeLeavesSummarySerializer(serializers.Serializer):
    employee_id = serializers.IntegerField()
    employee_name = serializers.CharField()
    employee_code = serializers.CharField()
    month = serializers.IntegerField()
    year = serializers.IntegerField()
    total_days = serializers.IntegerField()
    present_days = serializers.IntegerField()
    weekoff_days = serializers.IntegerField()
    weekoff_halfday_days = serializers.IntegerField(required=False, default=0)
    company_week_off_days = serializers.IntegerField(required=False, default=0)
    leave_days = serializers.IntegerField()
    half_day_days = serializers.IntegerField(required=False, default=0)
    permission_days = serializers.IntegerField(required=False, default=0)
    effective_leave_days = serializers.FloatField(required=False, default=0.0)
    leave_deduction = serializers.FloatField()
    gross_salary = serializers.FloatField(required=False, default=0.0)
    net_payable = serializers.FloatField(required=False, default=0.0)
    is_joining_month = serializers.BooleanField(required=False, default=False)
    date_of_joining = serializers.CharField(required=False, allow_null=True, default=None)
