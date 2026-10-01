import logging
import razorpay
from django.conf import settings
from django.db import transaction
from app.exceptions import BadRequestError, ConflictError, NotFoundError
from app.models.payment import PaymentOrder
from app.models.user import User

logger = logging.getLogger(__name__)

PLAN_PRICES = {
    "professional": 49900,  # ₹499 in paise
    "enterprise": 99900,    # ₹999 in paise
}


def _get_razorpay_client():
    if not settings.RAZORPAY_KEY_ID or not settings.RAZORPAY_KEY_SECRET:
        raise BadRequestError("Razorpay API keys are not configured on the server.")
    return razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))


def create_order(user: User, plan_name: str) -> dict:
    if plan_name not in PLAN_PRICES:
        raise BadRequestError(f"Invalid plan name: {plan_name}")

    amount = PLAN_PRICES[plan_name]
    client = _get_razorpay_client()

    try:
        razorpay_order = client.order.create({
            "amount": amount,
            "currency": "INR",
            "payment_capture": 1,
            "notes": {
                "user_id": user.id,
                "user_email": user.email,
                "plan_name": plan_name,
            }
        })
    except Exception as e:
        logger.error("Failed to create Razorpay order: %s", str(e))
        raise BadRequestError(f"Failed to create payment order: {str(e)}")

    payment_order = PaymentOrder.objects.create(
        user=user,
        razorpay_order_id=razorpay_order["id"],
        plan_name=plan_name,
        amount=amount,
        status="created"
    )

    return {
        "payment_order": payment_order,
        "razorpay_order": razorpay_order,
        "razorpay_key_id": settings.RAZORPAY_KEY_ID,
    }


def verify_payment(user: User, razorpay_order_id: str, razorpay_payment_id: str, razorpay_signature: str) -> dict:
    with transaction.atomic():
        try:
            payment_order = PaymentOrder.objects.select_for_update().get(
                razorpay_order_id=razorpay_order_id,
                user=user,
            )
        except PaymentOrder.DoesNotExist:
            raise NotFoundError("Payment order")

        if payment_order.status != "created":
            raise ConflictError("Payment order has already been processed.")

        expected_amount = PLAN_PRICES.get(payment_order.plan_name)
        if expected_amount is None or payment_order.amount != expected_amount:
            logger.error("Stored payment order %s failed plan/amount validation", razorpay_order_id)
            raise BadRequestError("Payment order details are invalid.")

        try:
            client = _get_razorpay_client()
            client.utility.verify_payment_signature({
                "razorpay_order_id": payment_order.razorpay_order_id,
                "razorpay_payment_id": razorpay_payment_id,
                "razorpay_signature": razorpay_signature,
            })
        except Exception:
            logger.warning("Payment signature verification failed for order %s", razorpay_order_id)
            raise BadRequestError("Invalid payment signature.")

        payment_order.razorpay_payment_id = razorpay_payment_id
        payment_order.razorpay_signature = razorpay_signature
        payment_order.status = "paid"
        payment_order.save(update_fields=[
            "razorpay_payment_id",
            "razorpay_signature",
            "status",
            "updated_at",
        ])

        from datetime import timedelta
        from django.utils import timezone

        user.plan = payment_order.plan_name
        now = timezone.now()
        current_expiry = user.plan_expires_at
        # If renewing while existing paid plan is still active, extend by 30 days from expiry
        if current_expiry and current_expiry > now:
            user.plan_expires_at = current_expiry + timedelta(days=30)
        else:
            user.plan_expires_at = now + timedelta(days=30)
        user.save(update_fields=["plan", "plan_expires_at", "updated_at"])

    user.refresh_from_db()
    logger.info("User %s successfully upgraded to plan: %s in database", user.email, user.plan)

    from app.serializers.auth import UserResponseSerializer
    return {
        "message": f"Payment successful! Plan upgraded to {payment_order.plan_name.upper()}.",
        "plan": user.plan,
        "payment_order_id": payment_order.id,
        "user": UserResponseSerializer(user).data,
    }


def get_user_payment_history(user: User):
    return PaymentOrder.objects.filter(user=user).order_by("-created_at")
