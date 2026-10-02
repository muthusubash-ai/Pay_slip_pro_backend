from django.contrib import admin
from app.models.user import User
from app.models.company import Company
from app.models.employee import Employee
from app.models.salary_slip import SalarySlip
from app.models.attendance import Attendance
from app.models.payment import PaymentOrder


class CompanyFilter(admin.SimpleListFilter):
    title = "Company"
    parameter_name = "company_user_id"

    def lookups(self, request, model_admin):
        companies = Company.objects.all().order_by("company_name")
        return [(c.user_id, c.company_name) for c in companies]

    def queryset(self, request, queryset):
        if self.value():
            # If the queryset is for User model, user id is 'id'
            if queryset.model == User:
                return queryset.filter(id=self.value())
            # Matches user_id on Employee, SalarySlip, Attendance, PaymentOrder
            return queryset.filter(user_id=self.value())
        return queryset


class CompanyInline(admin.StackedInline):
    model = Company
    can_delete = False
    extra = 0
    fields = ("company_name", "pay_day", "financial_year_start", "address", "city", "state", "zip_code")


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    inlines = [CompanyInline]
    list_display = (
        "id",
        "email",
        "full_name",
        "get_company_name",
        "role",
        "plan",
        "plan_expires_at",
        "is_plan_expired_badge",
        "is_platform_admin",
        "auth_provider",
        "is_active",
        "created_at",
    )
    search_fields = ("email", "full_name", "company__company_name")
    list_filter = (CompanyFilter, "role", "plan", "is_platform_admin", "is_active")
    fields = (
        "email",
        "full_name",
        "role",
        "is_platform_admin",
        "is_active",
        "plan",
        "plan_expires_at",
        "phone",
        "auth_provider",
        "password",
        "admin_password",
    )

    def save_model(self, request, obj, form, change):
        # Auto-hash plain text passwords if edited directly in Django admin
        if "admin_password" in form.changed_data:
            raw_admin = form.cleaned_data.get("admin_password")
            if raw_admin and not raw_admin.startswith("$2b$") and not raw_admin.startswith("pbkdf2_"):
                obj.set_admin_password(raw_admin)
        if "password" in form.changed_data:
            raw_pass = form.cleaned_data.get("password")
            if raw_pass and not raw_pass.startswith("$2b$") and not raw_pass.startswith("pbkdf2_"):
                obj.set_password(raw_pass)
        super().save_model(request, obj, form, change)

    @admin.display(description="Company Name", ordering="company__company_name")
    def get_company_name(self, obj):
        company = getattr(obj, "company", None)
        return company.company_name if company else "-"

    @admin.display(description="Plan Expired?", boolean=True)
    def is_plan_expired_badge(self, obj):
        return obj.is_plan_expired



@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ("id", "company_name", "get_user_email", "pay_day", "financial_year_start", "created_at")
    search_fields = ("company_name", "user__email", "user__full_name")

    @admin.display(description="HR User Email", ordering="user__email")
    def get_user_email(self, obj):
        return obj.user.email if obj.user else "-"


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "employee_code",
        "full_name",
        "get_company_name",
        "email",
        "department",
        "designation",
        "basic_salary",
        "is_active",
    )
    search_fields = ("employee_code", "full_name", "email", "user__company__company_name", "user__email")
    list_filter = (CompanyFilter, "department", "is_active")

    @admin.display(description="Company", ordering="user__company__company_name")
    def get_company_name(self, obj):
        if obj.user:
            company = getattr(obj.user, "company", None)
            return company.company_name if company else obj.user.email
        return "-"


@admin.register(SalarySlip)
class SalarySlipAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "employee",
        "get_company_name",
        "month",
        "year",
        "gross_salary",
        "total_deductions",
        "net_pay",
        "status",
        "generated_at",
    )
    search_fields = ("employee__full_name", "employee__employee_code", "user__company__company_name", "user__email")
    list_filter = (CompanyFilter, "month", "year", "status")

    @admin.display(description="Company", ordering="user__company__company_name")
    def get_company_name(self, obj):
        if obj.user:
            company = getattr(obj.user, "company", None)
            return company.company_name if company else obj.user.email
        return "-"


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ("id", "employee", "get_company_name", "date", "status")
    search_fields = ("employee__full_name", "employee__employee_code", "user__company__company_name", "user__email")
    list_filter = (CompanyFilter, "status", "date")

    @admin.display(description="Company", ordering="user__company__company_name")
    def get_company_name(self, obj):
        if obj.user:
            company = getattr(obj.user, "company", None)
            return company.company_name if company else obj.user.email
        return "-"


@admin.register(PaymentOrder)
class PaymentOrderAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "razorpay_order_id",
        "get_company_name",
        "user",
        "plan_name",
        "amount",
        "status",
        "razorpay_payment_id",
        "created_at",
    )
    search_fields = ("razorpay_order_id", "razorpay_payment_id", "user__company__company_name", "user__email")
    list_filter = (CompanyFilter, "status", "plan_name")

    @admin.display(description="Company", ordering="user__company__company_name")
    def get_company_name(self, obj):
        if obj.user:
            company = getattr(obj.user, "company", None)
            return company.company_name if company else obj.user.email
        return "-"

