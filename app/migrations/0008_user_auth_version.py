from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("app", "0007_user_phone")]

    operations = [
        migrations.AddField(
            model_name="user",
            name="auth_version",
            field=models.PositiveIntegerField(default=0),
        ),
    ]
