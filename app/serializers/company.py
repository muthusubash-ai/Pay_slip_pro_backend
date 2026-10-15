from rest_framework import serializers
from app.models.company import Company


class CompanyUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        fields = [
            "company_name",
            "logo_data",
            "primary_color",
            "address",
            "city",
            "state",
            "zip_code",
            "pay_day",
            "financial_year_start",
            "pf_number",
            "tan_number",
            "office_lat",
            "office_lng",
            "allowed_radius_meters",
            "weekly_off_days",
            "permission_days_per_month",
            "office_timing",
            "office_start_time",
            "office_end_time",
            "enable_employee_shift_timing",
        ]
        extra_kwargs = {
            field: {"required": False, "allow_null": True}
            for field in fields
        }

    def validate_weekly_off_days(self, value):
        if value is None:
            return []
        if not isinstance(value, list) or any(not isinstance(d, int) or d < 0 or d > 6 for d in value):
            raise serializers.ValidationError("weekly_off_days must be a list of integers 0 (Monday) to 6 (Sunday).")
        return sorted(set(value))

    def validate_permission_days_per_month(self, value):
        if value is None:
            return 3
        if not isinstance(value, int) or value < 0 or value > 31:
            raise serializers.ValidationError("permission_days_per_month must be an integer between 0 and 31.")
        return value


class CompanyResponseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        fields = [
            "id",
            "company_name",
            "logo_url",
            "logo_data",
            "primary_color",
            "address",
            "city",
            "state",
            "zip_code",
            "pay_day",
            "financial_year_start",
            "pf_number",
            "tan_number",
            "office_lat",
            "office_lng",
            "allowed_radius_meters",
            "weekly_off_days",
            "permission_days_per_month",
            "office_timing",
            "office_start_time",
            "office_end_time",
            "enable_employee_shift_timing",
        ]
