from django.contrib import admin
from app.models.user import User
from app.models.company import Company
from app.models.employee import Employee
from app.models.salary_slip import SalarySlip
from app.models.attendance import Attendance
from app.models.payment import PaymentOrder


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("email", "full_name", "role", "plan", "auth_provider", "is_active", "created_at")
    search_fields = ("email", "full_name")
    list_filter = ("role", "plan", "is_active")


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ("company_name", "company_email", "phone_number", "created_at")
    search_fields = ("company_name", "company_email")


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ("employee_id", "full_name", "email", "designation", "department", "company")
    search_fields = ("employee_id", "full_name", "email")


@admin.register(SalarySlip)
class SalarySlipAdmin(admin.ModelAdmin):
    list_display = ("slip_number", "employee", "company", "month", "year", "net_salary")
    list_filter = ("month", "year")


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ("employee", "company", "month", "year", "present_days", "leave_days")


@admin.register(PaymentOrder)
class PaymentOrderAdmin(admin.ModelAdmin):
    list_display = ("order_id", "user", "plan", "amount", "status", "payment_id", "created_at")
    list_filter = ("status", "plan")
