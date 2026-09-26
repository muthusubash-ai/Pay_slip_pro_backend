from rest_framework import serializers
from app.models.attendance import Attendance


class AttendanceCreateSerializer(serializers.Serializer):
    employee_id = serializers.IntegerField()
    date = serializers.DateField()
    status = serializers.CharField()


class AttendanceBulkCreateSerializer(serializers.Serializer):
    employee_id = serializers.IntegerField()
    month = serializers.IntegerField()
    year = serializers.IntegerField()
    leave_dates = serializers.ListField(child=serializers.DateField())
    weekoff_dates = serializers.ListField(child=serializers.DateField(), required=False, default=[])


class AttendanceResponseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Attendance
        fields = ["id", "employee_id", "date", "status"]


class EmployeeLeavesSummarySerializer(serializers.Serializer):
    employee_id = serializers.IntegerField()
    employee_name = serializers.CharField()
    employee_code = serializers.CharField()
    month = serializers.IntegerField()
    year = serializers.IntegerField()
    total_days = serializers.IntegerField()
    leave_days = serializers.IntegerField()
    weekoff_days = serializers.IntegerField()
    present_days = serializers.IntegerField()
    leave_deduction = serializers.FloatField()
