from datetime import timedelta
from django.db import migrations
from django.utils import timezone


def backfill_plan_expiry(apps, schema_editor):
    User = apps.get_model("app", "User")
    PaymentOrder = apps.get_model("app", "PaymentOrder")

    # Find existing paid users who are not platform admins and have no expiry set
    paid_users = User.objects.filter(
        plan__in=["professional", "enterprise"],
        is_platform_admin=False,
        plan_expires_at__isnull=True,
    )

    now = timezone.now()
    for user in paid_users:
        # Check their latest successful payment
        last_payment = (
            PaymentOrder.objects.filter(user=user, status="paid")
            .order_by("-created_at")
            .first()
        )
        if last_payment and last_payment.created_at:
            calculated_expiry = last_payment.created_at + timedelta(days=30)
            # If payment was less than 30 days ago, set the remaining expiry
            # If payment was older than 30 days, grant a 30-day grace period from migration time
            if calculated_expiry > now:
                user.plan_expires_at = calculated_expiry
            else:
                user.plan_expires_at = now + timedelta(days=30)
        else:
            # If no payment record found (e.g. manual plan assignment), grant 30 days from now
            user.plan_expires_at = now + timedelta(days=30)
        user.save(update_fields=["plan_expires_at"])


def reverse_backfill(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0011_user_plan_expires_at"),
    ]

    operations = [
        migrations.RunPython(backfill_plan_expiry, reverse_backfill),
    ]
