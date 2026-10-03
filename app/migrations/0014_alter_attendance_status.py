from django.db import migrations, models


def add_enum_values(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        with schema_editor.connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_type WHERE typname = 'attendancestatus';")
            if cursor.fetchone():
                cursor.execute("ALTER TYPE attendancestatus ADD VALUE IF NOT EXISTS 'weekoff_halfday';")


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0013_user_admin_password"),
    ]

    operations = [
        migrations.RunPython(add_enum_values, reverse_code=migrations.RunPython.noop),
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
                    ("weekoff_halfday", "weekoff_halfday"),
                ],
                default="present",
                max_length=20,
            ),
        ),
    ]
