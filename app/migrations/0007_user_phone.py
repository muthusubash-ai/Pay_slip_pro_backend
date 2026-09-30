from django.db import migrations, models

class Migration(migrations.Migration):

    dependencies = [
        ("app", "0006_attendance_half_day_permission"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="phone",
            field=models.CharField(blank=True, max_length=20, null=True),
        ),
    ]
