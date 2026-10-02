from django.core.management.base import BaseCommand, CommandError
from app.models.user import User


class Command(BaseCommand):
    help = "Set the separate Django Admin password for a platform admin user."

    def add_arguments(self, parser):
        parser.add_argument("email", type=str, help="Email address of the admin user")
        parser.add_argument("password", type=str, help="New Django Admin password")

    def handle(self, *args, **options):
        email = options["email"].strip().lower()
        password = options["password"]

        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            raise CommandError(f"User with email '{email}' does not exist.")

        user.is_platform_admin = True
        user.set_admin_password(password)
        user.save(update_fields=["is_platform_admin", "admin_password", "updated_at"])

        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully set Django Admin password for '{email}'.\n"
                f"NOTE: This password is ONLY used for Django Admin (/admin/).\n"
                f"The web application login (/login) password remains completely independent."
            )
        )
