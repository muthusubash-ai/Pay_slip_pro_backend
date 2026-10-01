from rest_framework import serializers
from app.models.user import User


import re

class RegisterRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)
    full_name = serializers.CharField()
    phone = serializers.CharField(required=False, allow_blank=True, default="")

    def validate_full_name(self, value):
        val = value.strip()
        if not re.match(r"^[a-zA-Z\s.'-]+$", val):
            raise serializers.ValidationError("Full name must contain only letters and spaces.")
        return val


class RefreshRequestSerializer(serializers.Serializer):
    refresh_token = serializers.CharField()


class ForgotPasswordRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class ResetPasswordRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()
    token = serializers.CharField()
    new_password = serializers.CharField(write_only=True)


class UpdateProfileRequestSerializer(serializers.Serializer):
    full_name = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    company_name = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    phone = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    def validate_full_name(self, value):
        if not value:
            return value
        val = value.strip()
        if not re.match(r"^[a-zA-Z\s.'-]+$", val):
            raise serializers.ValidationError("Full name must contain only letters and spaces.")
        return val

    def validate(self, attrs):
        if "role" in self.initial_data:
            raise serializers.ValidationError({
                "role": "Role cannot be changed through the profile endpoint."
            })
        return attrs


class UserResponseSerializer(serializers.ModelSerializer):
    company_name = serializers.CharField(read_only=True)

    class Meta:
        model = User
        fields = ["id", "email", "full_name", "phone", "company_name", "role", "plan", "plan_expires_at", "is_active", "is_platform_admin", "created_at"]
