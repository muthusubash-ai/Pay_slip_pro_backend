from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0009_user_platform_admin"),
    ]

    operations = [
        migrations.AlterField(
            model_name="attendance",
            name="status",
            field=models.CharField(
                choices=[
                    ("present", "present"),
                    ("leave", "leave"),
                    ("weekoff", "weekoff"),
                    ("half_day", "half_day"),
                    ("permission", "permission"),
                ],
                default="present",
                max_length=20,
            ),
        ),
    ]
