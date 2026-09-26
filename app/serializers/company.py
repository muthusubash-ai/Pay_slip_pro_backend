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
        ]
        extra_kwargs = {
            field: {"required": False, "allow_null": True}
            for field in fields
        }


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
        ]
