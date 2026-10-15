import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('attendance', '0006_leaverequest_duration_hours'), ('app', '0015_company_allowed_radius_meters_company_office_lat_and_more')]
    operations = [
        migrations.AlterField(model_name='employee', name='emp_id', field=models.CharField(max_length=20, db_index=True)),
        migrations.AddField(model_name='employee', name='payroll_employee', field=models.OneToOneField(null=True, blank=True, on_delete=django.db.models.deletion.CASCADE, related_name='attendance_account', to='app.employee')),
        migrations.AddField(model_name='employee', name='google_subject', field=models.CharField(max_length=255, blank=True, default='')),
        migrations.CreateModel(name='ActivationInvite', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('digest', models.CharField(max_length=64, unique=True)),
            ('email', models.EmailField(max_length=254)),
            ('expires_at', models.DateTimeField()),
            ('used', models.BooleanField(default=False)),
            ('payroll_employee', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='app.employee')),
        ]),
        migrations.CreateModel(name='EmployeeSession', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('digest', models.CharField(max_length=64, unique=True)),
            ('expires_at', models.DateTimeField()),
            ('employee', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='attendance.employee')),
        ]),
    ]
