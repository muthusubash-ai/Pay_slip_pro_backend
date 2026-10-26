from django.core.management.base import BaseCommand

from app.models.user import User
from app.services.plan_notification_service import check_and_notify_plan_expiry


class Command(BaseCommand):
    help = (
        "Email HR for every non-starter plan that is expiring soon or has expired. "
        "This also runs lazily on dashboard load, but a daily cron covers accounts "
        "that never open the app before their plan lapses."
    )

    def handle(self, *args, **options):
        users = User.objects.filter(is_active=True).exclude(plan="starter").exclude(plan_expires_at__isnull=True)
        sent = 0
        for user in users:
            if check_and_notify_plan_expiry(user):
                sent += 1
        self.stdout.write(self.style.SUCCESS(f"Checked {users.count()} user(s), sent {sent} notice(s)."))
