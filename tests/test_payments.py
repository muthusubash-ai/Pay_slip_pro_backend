from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.models.payment import PaymentOrder
from app.models.user import User


def _starter_user():
    user = User.objects.get(email="test@example.com")
    user.plan = "starter"
    user.save(update_fields=["plan", "updated_at"])
    return user


def _payment_order(user, order_id="order_test_123"):
    return PaymentOrder.objects.create(
        user=user,
        razorpay_order_id=order_id,
        plan_name="professional",
        amount=49900,
        status="created",
    )


def test_demo_signature_cannot_upgrade_plan(client, auth_headers):
    user = _starter_user()
    order = _payment_order(user)
    verifier = Mock(side_effect=Exception("invalid signature"))

    with patch(
        "app.services.payment_service._get_razorpay_client",
        return_value=SimpleNamespace(utility=SimpleNamespace(verify_payment_signature=verifier)),
    ):
        response = client.post(
            "/api/v1/payments/verify",
            json={
                "razorpay_order_id": order.razorpay_order_id,
                "razorpay_payment_id": "pay_fake",
                "razorpay_signature": "demo_test_signature",
            },
            headers=auth_headers,
        )

    assert response.status_code == 400
    user.refresh_from_db()
    order.refresh_from_db()
    assert user.plan == "starter"
    assert order.status == "created"


def test_unknown_order_id_does_not_fall_back_to_latest_order(client, auth_headers):
    user = _starter_user()
    order = _payment_order(user)

    response = client.post(
        "/api/v1/payments/verify",
        json={
            "razorpay_order_id": "order_not_owned_or_missing",
            "razorpay_payment_id": "pay_fake",
            "razorpay_signature": "signature_fake",
        },
        headers=auth_headers,
    )

    assert response.status_code == 404
    user.refresh_from_db()
    order.refresh_from_db()
    assert user.plan == "starter"
    assert order.status == "created"


def test_valid_razorpay_signature_upgrades_plan(client, auth_headers):
    user = _starter_user()
    order = _payment_order(user)
    verifier = Mock(return_value=None)

    with patch(
        "app.services.payment_service._get_razorpay_client",
        return_value=SimpleNamespace(utility=SimpleNamespace(verify_payment_signature=verifier)),
    ):
        response = client.post(
            "/api/v1/payments/verify",
            json={
                "razorpay_order_id": order.razorpay_order_id,
                "razorpay_payment_id": "pay_valid_123",
                "razorpay_signature": "valid_signature",
            },
            headers=auth_headers,
        )

    assert response.status_code == 200
    user.refresh_from_db()
    order.refresh_from_db()
    assert user.plan == "professional"
    assert order.status == "paid"
    assert order.razorpay_payment_id == "pay_valid_123"
    verifier.assert_called_once_with({
        "razorpay_order_id": order.razorpay_order_id,
        "razorpay_payment_id": "pay_valid_123",
        "razorpay_signature": "valid_signature",
    })


def test_paid_order_cannot_be_verified_twice(client, auth_headers):
    user = _starter_user()
    order = _payment_order(user)
    order.status = "paid"
    order.save(update_fields=["status", "updated_at"])

    response = client.post(
        "/api/v1/payments/verify",
        json={
            "razorpay_order_id": order.razorpay_order_id,
            "razorpay_payment_id": "pay_replay",
            "razorpay_signature": "replayed_signature",
        },
        headers=auth_headers,
    )

    assert response.status_code == 409
    user.refresh_from_db()
    assert user.plan == "starter"
