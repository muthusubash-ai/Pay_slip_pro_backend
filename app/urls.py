from django.contrib import admin
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from app import views

# Create a router for viewsets
router = DefaultRouter()
# We will register viewsets here (e.g. EmployeeViewSet, SalarySlipViewSet)

urlpatterns = [
    # Django Built-in Admin Panel
    path("admin/", admin.site.urls),

    # Router endpoints
    # Router endpoints
    path("api/v1/", include(router.urls)),
    path("api/v1/health", views.health_check, name="health_check"),
    
    # Custom Auth Routes
    path("api/v1/auth/register", views.AuthViews.register, name="auth_register"),
    path("api/v1/auth/login", views.AuthViews.login, name="auth_login"),
    path("api/v1/auth/refresh", views.AuthViews.refresh, name="auth_refresh"),
    path("api/v1/auth/logout", views.AuthViews.logout, name="auth_logout"),
    path("api/v1/auth/csrf", views.AuthViews.csrf, name="auth_csrf"),
    path("api/v1/auth/me", views.AuthViews.me, name="auth_me"),
    path("api/v1/auth/forgot-password", views.AuthViews.forgot_password, name="auth_forgot_password"),
    path("api/v1/auth/reset-password", views.AuthViews.reset_password, name="auth_reset_password"),
    path("api/v1/auth/google/login", views.AuthViews.google_login, name="auth_google_login"),
    path("api/v1/auth/google/callback", views.AuthViews.google_callback, name="auth_google_callback"),
    
    # Custom Company Routes
    path("api/v1/company/", views.CompanyViews.company_detail, name="company_detail"),
    path("api/v1/company/logo", views.CompanyViews.company_logo, name="company_logo"),
    
    # Custom Employee Routes
    path("api/v1/employees/", views.EmployeeViews.employee_list_create, name="employee_list_create"),
    path("api/v1/employees/<int:employee_id>", views.EmployeeViews.employee_detail, name="employee_detail"),
    
    # Custom Salary Slip Routes
    path("api/v1/salary-slips/", views.SalarySlipViews.salary_slip_list, name="salary_slip_list"),
    path("api/v1/salary-slips/generate", views.SalarySlipViews.generate_slips, name="generate_slips"),
    path("api/v1/salary-slips/generate/<int:employee_id>", views.SalarySlipViews.generate_single_slip, name="generate_single_slip"),
    path("api/v1/salary-slips/<int:slip_id>/pdf", views.SalarySlipViews.download_pdf, name="download_pdf"),
    path("api/v1/salary-slips/<int:slip_id>/email", views.SalarySlipViews.email_slip, name="email_slip"),
    path("api/v1/salary-slips/<int:slip_id>/delete", views.SalarySlipViews.delete_slip, name="delete_slip"), # Note: FastAPI uses DELETE /salary-slips/{slip_id}
    path("api/v1/salary-slips/<int:slip_id>", views.SalarySlipViews.get_or_delete_slip, name="get_or_delete_slip"),
    
    # Custom Attendance Routes
    path("api/v1/attendance/", views.AttendanceViews.mark_attendance, name="mark_attendance"),
    path("api/v1/attendance/bulk", views.AttendanceViews.bulk_mark_leaves, name="bulk_mark_leaves"),
    path("api/v1/attendance/monthly", views.AttendanceViews.get_monthly_attendance, name="get_monthly_attendance"),
    path("api/v1/attendance/leave-summary", views.AttendanceViews.get_leave_summary, name="get_leave_summary"),
    
    # Custom Dashboard Routes
    path("api/v1/dashboard/stats", views.DashboardViews.get_stats, name="dashboard_stats"),
    path("api/v1/dashboard/payroll-summary", views.DashboardViews.get_payroll_summary, name="dashboard_payroll_summary"),
    path("api/v1/dashboard/department-breakdown", views.DashboardViews.get_department_breakdown, name="dashboard_department_breakdown"),
    
    # Custom Admin Routes
    path("api/v1/admin/users", views.AdminViews.list_users, name="admin_list_users"),
    path("api/v1/admin/users/<int:user_id>", views.AdminViews.update_or_delete_user, name="admin_update_or_delete_user"),
    path("api/v1/admin/stats", views.AdminViews.platform_stats, name="admin_platform_stats"),

    # Custom Payment Routes
    path("api/v1/payments/create-order", views.PaymentViews.create_order, name="payment_create_order"),
    path("api/v1/payments/verify", views.PaymentViews.verify_payment, name="payment_verify"),
    path("api/v1/payments/history", views.PaymentViews.payment_history, name="payment_history"),

    # Root Redirect
    path("", views.root_view, name="root_view"),
]
