from django.contrib import admin
from app.models.user import User
from app.models.company import Company
from app.models.employee import Employee
from app.models.salary_slip import SalarySlip
from app.models.attendance import Attendance
from app.models.payment import PaymentOrder


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("id", "email", "full_name", "role", "plan", "auth_provider", "is_active", "created_at")
    search_fields = ("email", "full_name")
    list_filter = ("role", "plan", "is_active")


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ("id", "company_name", "user", "pay_day", "financial_year_start", "created_at")
    search_fields = ("company_name",)


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ("id", "employee_code", "full_name", "email", "department", "designation", "basic_salary", "user", "is_active")
    search_fields = ("employee_code", "full_name", "email")
    list_filter = ("department", "is_active")


@admin.register(SalarySlip)
class SalarySlipAdmin(admin.ModelAdmin):
    list_display = ("id", "employee", "user", "month", "year", "gross_salary", "total_deductions", "net_pay", "status", "generated_at")
    list_filter = ("month", "year", "status")


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ("id", "employee", "user", "date", "status")
    list_filter = ("status", "date")


@admin.register(PaymentOrder)
class PaymentOrderAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "razorpay_order_id",
        "user",
        "plan_name",
        "amount",
        "status",
        "razorpay_payment_id",
        "created_at",
    )
    list_filter = ("status", "plan_name")
