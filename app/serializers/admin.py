from rest_framework import serializers
from app.models.user import User


class UserAdminResponseSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "email", "full_name", "role", "plan", "is_active", "created_at"]


class UpdateUserRoleRequestSerializer(serializers.Serializer):
    role = serializers.CharField(required=False, allow_null=True)
    is_active = serializers.BooleanField(required=False, allow_null=True)


class PlatformStatsSerializer(serializers.Serializer):
    total_users = serializers.IntegerField()
    active_users = serializers.IntegerField()
    total_employees = serializers.IntegerField()
    total_slips = serializers.IntegerField()
