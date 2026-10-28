from rest_framework import serializers
from app.models.user import User


class UserAdminResponseSerializer(serializers.ModelSerializer):
    company_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "email", "full_name", "role", "plan", "is_active", "created_at", "company_name"]

    def get_company_name(self, obj):
        try:
            return obj.company.company_name if hasattr(obj, "company") and obj.company else "-"
        except Exception:
            return "-"


class UpdateUserRoleRequestSerializer(serializers.Serializer):
    role = serializers.CharField(required=False, allow_null=True)
    is_active = serializers.BooleanField(required=False, allow_null=True)


class PlatformStatsSerializer(serializers.Serializer):
    total_users = serializers.IntegerField()
    active_users = serializers.IntegerField()
    total_employees = serializers.IntegerField()
    total_slips = serializers.IntegerField()
