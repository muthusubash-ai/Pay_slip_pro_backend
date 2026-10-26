import logging
from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger(__name__)


def _expiry_stage(expires_at, now):
    """Mirror the thresholds the Header notification bell already uses, so the
    email and the in-app bell agree on when a plan counts as expiring/expired."""
    diff = expires_at - now
    if diff.total_seconds() <= 0:
        return "expired"
    if diff <= timedelta(hours=24):
        return "24h"
    if diff <= timedelta(hours=48):
        return "48h"
    if diff <= timedelta(days=7):
        return "7d"
    return None


_WHEN_TEXT = {
    "7d": lambda diff: f"{max(1, diff.days)} day{'s' if diff.days != 1 else ''}",
    "48h": lambda diff: "1 day",
    "24h": lambda diff: f"{max(1, int(diff.total_seconds() // 3600))} hour(s)",
    "expired": lambda diff: "",
}


def check_and_notify_plan_expiry(user) -> bool:
    """Lazily check this user's plan expiry and email HR once per stage. Safe to
    call on every dashboard/stats request - the DB-level claim below means only
    one caller ever actually sends, even under concurrent requests.

    Returns True if a notice was sent (or attempted), False if nothing was due.
    """
    if not user or getattr(user, "plan", "starter") == "starter" or not user.plan_expires_at:
        return False

    now = timezone.now()
    stage = _expiry_stage(user.plan_expires_at, now)
    if not stage:
        return False

    new_key = f"{stage}:{user.plan_expires_at.isoformat()}"
    from app.models.user import User

    # Atomic claim: only the caller that flips plan_expiry_notice_key from its
    # current value to new_key actually sends - everyone else sees 0 rows
    # updated and skips. A plan renewal changes plan_expires_at, so new_key
    # differs and the notice cycle starts fresh on its own.
    previous_key = user.plan_expiry_notice_key
    claimed = User.objects.filter(pk=user.pk, plan_expiry_notice_key=previous_key).exclude(
        plan_expiry_notice_key=new_key
    ).update(plan_expiry_notice_key=new_key)
    if not claimed:
        return False

    try:
        from app.services.email_service import send_plan_expiry_notice_email

        when = _WHEN_TEXT.get(stage, lambda diff: "")(user.plan_expires_at - now)
        send_plan_expiry_notice_email(
            to_email=user.effective_notification_email,
            plan_name=str(user.plan).title(),
            stage=stage,
            expires_at_str=user.plan_expires_at.strftime("%d %b %Y, %I:%M %p"),
            when=when,
            company_name=user.company_name,
        )
    except Exception:
        logger.warning("Plan-expiry notice delivery failed for user %s", user.pk, exc_info=True)
    return True
