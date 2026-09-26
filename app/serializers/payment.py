from rest_framework import serializers
from app.models.payment import PaymentOrder


class CreatePaymentOrderSerializer(serializers.Serializer):
    plan_name = serializers.ChoiceField(choices=["professional", "enterprise"])


class VerifyPaymentSerializer(serializers.Serializer):
    razorpay_order_id = serializers.CharField(max_length=255)
    razorpay_payment_id = serializers.CharField(max_length=255)
    razorpay_signature = serializers.CharField(max_length=255)


class PaymentOrderResponseSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentOrder
        fields = [
            "id",
            "razorpay_order_id",
            "razorpay_payment_id",
            "plan_name",
            "amount",
            "status",
            "created_at",
        ]
