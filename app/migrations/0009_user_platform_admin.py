from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0008_user_auth_version"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="is_platform_admin",
            field=models.BooleanField(default=False),
        ),
    ]
