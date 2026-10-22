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

    def validate_pay_day(self, value):
        if value is None:
            return 1
        if not isinstance(value, int) or value < 1 or value > 31:
            raise serializers.ValidationError("pay_day must be an integer between 1 and 31.")
        return value

    def validate_financial_year_start(self, value):
        if value is None:
            return 4
        if not isinstance(value, int) or value < 1 or value > 12:
            raise serializers.ValidationError("financial_year_start must be a month number between 1 and 12.")
        return value

    def validate_allowed_radius_meters(self, value):
        if value is None:
            return value
        if not isinstance(value, int) or value < 1 or value > 50000:
            raise serializers.ValidationError("allowed_radius_meters must be an integer between 1 and 50000.")
        return value

    def validate_office_lat(self, value):
        if value is None:
            return value
        if not isinstance(value, (int, float)) or not -90 <= value <= 90:
            raise serializers.ValidationError("office_lat must be a valid latitude between -90 and 90.")
        return value

    def validate_office_lng(self, value):
        if value is None:
            return value
        if not isinstance(value, (int, float)) or not -180 <= value <= 180:
            raise serializers.ValidationError("office_lng must be a valid longitude between -180 and 180.")
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
