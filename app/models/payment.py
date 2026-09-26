from django.db import models
from app.models.user import User
from app.models.base import TimestampModel


class PaymentOrder(TimestampModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="payments")
    razorpay_order_id = models.CharField(max_length=255, unique=True)
    razorpay_payment_id = models.CharField(max_length=255, null=True, blank=True)
    razorpay_signature = models.CharField(max_length=255, null=True, blank=True)
    plan_name = models.CharField(max_length=50)  # professional, enterprise
    amount = models.IntegerField()  # Amount in paise (e.g. 99900 for ₹999)
    status = models.CharField(max_length=20, default="created")  # created, paid, failed

    class Meta:
        db_table = "payment_orders"

    def __str__(self):
        return f"{self.user.email} - {self.plan_name} - {self.status}"
