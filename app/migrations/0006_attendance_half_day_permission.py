from django.db import migrations


def add_enum_values(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        with schema_editor.connection.cursor() as cursor:
            cursor.execute("ALTER TYPE attendancestatus ADD VALUE IF NOT EXISTS 'half_day';")
            cursor.execute("ALTER TYPE attendancestatus ADD VALUE IF NOT EXISTS 'permission';")


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0005_user_plan_paymentorder'),
    ]

    operations = [
        migrations.RunPython(add_enum_values, reverse_code=migrations.RunPython.noop),
    ]
