import logging
import base64
import io
from collections import Counter
from PIL import Image as PILImage
from datetime import datetime
from django.conf import settings
from django.http import HttpResponse, Http404
from django.shortcuts import redirect
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser


def _extract_dominant_color(img: PILImage.Image) -> str:
    """Extract the most prominent non-white/non-black color from an image."""
    small = img.copy()
    small.thumbnail((100, 100), PILImage.LANCZOS)
    quantized = small.quantize(colors=16, method=PILImage.Quantize.MEDIANCUT)
    palette = quantized.getpalette()
    if not palette:
        return "#000000"

    pixel_counts = Counter(quantized.getdata())
    color_counts = []
    for idx, count in pixel_counts.most_common():
        r, g, b = palette[idx * 3], palette[idx * 3 + 1], palette[idx * 3 + 2]
        brightness = (r + g + b) / 3
        if brightness > 235 or brightness < 20:
            continue
        max_c = max(r, g, b)
        min_c = min(r, g, b)
        if max_c - min_c < 15 and brightness > 100:
            continue
        color_counts.append(((r, g, b), count))

    if not color_counts:
        for idx, count in pixel_counts.most_common():
            r, g, b = palette[idx * 3], palette[idx * 3 + 1], palette[idx * 3 + 2]
            if (r + g + b) / 3 < 235:
                return f"#{r:02x}{g:02x}{b:02x}"
        return "#000000"

    r, g, b = color_counts[0][0]
    return f"#{r:02x}{g:02x}{b:02x}"


def _process_logo(image_bytes: bytes) -> tuple[str, str]:
    """Process logo: keep original aspect ratio, resize to max 1080px, extract dominant color."""
    img = PILImage.open(io.BytesIO(image_bytes))

    if img.mode in ("RGBA", "LA", "P"):
        bg = PILImage.new("RGB", img.size, (255, 255, 255))
        if img.mode == "P":
            img = img.convert("RGBA")
        if img.mode == "RGBA":
            bg.paste(img, mask=img.split()[3])
        else:
            bg.paste(img)
        img = bg
    else:
        img = img.convert("RGB")

    hex_color = _extract_dominant_color(img)
    img.thumbnail((1080, 1080), PILImage.LANCZOS)

    output = io.BytesIO()
    img.save(output, format="PNG", optimize=True)
    b64 = base64.b64encode(output.getvalue()).decode("utf-8")
    logo_data = f"data:image/png;base64,{b64}"

    return logo_data, hex_color

from app.auth.authentication import IsAdmin, IsAuthenticated
from app.exceptions import BadRequestError, ForbiddenError, UnauthorizedError
from app.models.user import UserRole
from app.models.employee import Employee
from app.plans import (
    PLAN_ENTERPRISE,
    PLAN_PROFESSIONAL,
    PLAN_STARTER,
    get_employee_limit,
    require_minimum_plan,
)
from app.serializers.auth import (
    RegisterRequestSerializer,
    LoginResponseSerializer,
    RefreshRequestSerializer,
    ForgotPasswordRequestSerializer,
    ResetPasswordRequestSerializer,
    UpdateProfileRequestSerializer,
    UserResponseSerializer,
)
from app.serializers.company import (
    CompanyUpdateSerializer,
    CompanyResponseSerializer,
)
from app.serializers.employee import (
    EmployeeCreateSerializer,
    EmployeeUpdateSerializer,
    EmployeeResponseSerializer,
    EmployeeListResponseSerializer,
)
from app.serializers.attendance import (
    AttendanceCreateSerializer,
    AttendanceBulkCreateSerializer,
    AttendanceResponseSerializer,
    EmployeeLeavesSummarySerializer,
)
from app.serializers.salary_slip import (
    GenerateSlipsRequestSerializer,
    SalarySlipResponseSerializer,
    SalarySlipListResponseSerializer,
)
from app.serializers.dashboard import (
    DashboardStatsSerializer,
    PayrollSummarySerializer,
    DepartmentBreakdownSerializer,
)
from app.serializers.admin import (
    UserAdminResponseSerializer,
    UpdateUserRoleRequestSerializer,
    PlatformStatsSerializer,
)
from app.services import (
    auth_service,
    company_service,
    employee_service,
    salary_service,
    attendance_service,
    dashboard_service,
    admin_service,
)

logger = logging.getLogger(__name__)


# -------------------------------------------------------------
# Auth Views
# -------------------------------------------------------------
class AuthViews:
    @staticmethod
    @api_view(["POST"])
    def register(request):
        serializer = RegisterRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = auth_service.register_user(
            None,
            serializer.validated_data["email"],
            serializer.validated_data["password"],
            serializer.validated_data["full_name"],
        )
        return Response(UserResponseSerializer(user).data, status=status.HTTP_201_CREATED)

    @staticmethod
    @api_view(["POST"])
    def login(request):
        # Support both form-data (from OAuth2PasswordRequestForm) and raw JSON
        username = request.data.get("username") or request.data.get("email")
        password = request.data.get("password")
        if not username or not password:
            raise BadRequestError("Username and password are required")
        res = auth_service.authenticate_user(None, username, password)
        return Response(res)

    @staticmethod
    @api_view(["POST"])
    def refresh(request):
        serializer = RefreshRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        res = auth_service.refresh_tokens(None, serializer.validated_data["refresh_token"])
        return Response(res)

    @staticmethod
    @api_view(["POST"])
    def logout(request):
        serializer = RefreshRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        auth_service.logout_user(None, serializer.validated_data["refresh_token"])
        return Response(status=status.HTTP_204_NO_CONTENT)

    @staticmethod
    @api_view(["GET", "PUT"])
    @permission_classes([IsAuthenticated])
    def me(request):
        if request.method == "GET":
            return Response(UserResponseSerializer(request.user).data)
        elif request.method == "PUT":
            serializer = UpdateProfileRequestSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            user = auth_service.update_profile(
                None,
                request.user,
                serializer.validated_data.get("full_name"),
                serializer.validated_data.get("role"),
            )
            return Response(UserResponseSerializer(user).data)

    @staticmethod
    @api_view(["POST"])
    def forgot_password(request):
        serializer = ForgotPasswordRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]
        code = auth_service.generate_reset_code(None, email)
        if code:
            from app.services.email_service import send_password_reset_email
            sent = send_password_reset_email(email, code)
            if sent:
                return Response({"message": "Reset code sent to your email.", "sent": True})
            return Response({"message": "Failed to send email. Check SMTP settings.", "sent": False})
        return Response({"message": "If the email exists, a reset code has been sent.", "sent": True})

    @staticmethod
    @api_view(["POST"])
    def reset_password(request):
        serializer = ResetPasswordRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        auth_service.reset_password_with_code(
            None,
            serializer.validated_data["email"],
            serializer.validated_data["token"],
            serializer.validated_data["new_password"],
        )
        return Response({"message": "Password reset successful. You can now login with your new password."})

    @staticmethod
    @api_view(["GET"])
    def google_login(request):
        from app.services.google_auth_service import get_google_login_url
        url = get_google_login_url()
        return redirect(url)

    @staticmethod
    @api_view(["GET"])
    def google_callback(request):
        from app.services.google_auth_service import (
            exchange_code_for_tokens,
            get_google_user_info,
            get_or_create_google_user,
            generate_tokens_for_user,
        )
        code = request.GET.get("code")
        if not code:
            raise BadRequestError("Code parameter is required")
        # Run async actions inside sync view
        import asyncio
        google_tokens = asyncio.run(exchange_code_for_tokens(code))
        google_user = asyncio.run(get_google_user_info(google_tokens["access_token"]))
        
        user = get_or_create_google_user(None, google_user)
        tokens = generate_tokens_for_user(None, user)
        
        redirect_url = (
            f"{settings.FRONTEND_URL}/auth/google/callback"
            f"?access_token={tokens['access_token']}"
            f"&refresh_token={tokens['refresh_token']}"
        )
        return redirect(redirect_url)


# -------------------------------------------------------------
# Company Views
# -------------------------------------------------------------
class CompanyViews:
    @staticmethod
    @api_view(["GET", "PUT"])
    @permission_classes([IsAuthenticated])
    def company_detail(request):
        require_minimum_plan(request.user, PLAN_PROFESSIONAL, "Company settings and branding")
        company = company_service.get_company(None, request.user)
        if request.method == "GET":
            if not company:
                return Response(None)
            return Response(CompanyResponseSerializer(company).data)
        elif request.method == "PUT":
            logger.info("Company PUT request data: %s", request.data)
            serializer = CompanyUpdateSerializer(data=request.data)
            if not serializer.is_valid():
                logger.error("Company validation failed: %s", serializer.errors)
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
            company = company_service.update_company(None, request.user, serializer.validated_data)
            logger.info("Company successfully updated: %s", company.company_name)
            return Response(CompanyResponseSerializer(company).data)

    @staticmethod
    @api_view(["POST", "DELETE"])
    @permission_classes([IsAuthenticated])
    @parser_classes([MultiPartParser, FormParser])
    def company_logo(request):
        require_minimum_plan(request.user, PLAN_PROFESSIONAL, "Custom company branding")
        company = company_service.get_company(None, request.user)
        if request.method == "POST":
            file_obj = request.FILES.get("file")
            if not file_obj:
                raise BadRequestError("No logo file uploaded")
            
            contents = file_obj.read()
            if len(contents) > settings.MAX_UPLOAD_SIZE:
                raise BadRequestError("Logo file must be under 5MB.")
                
            logo_data, hex_color = _process_logo(contents)
            
            if not company:
                from app.models.company import Company
                company = Company(user=request.user, company_name="My Company")
                company.save()
                
            company.logo_data = logo_data
            company.primary_color = hex_color
            company.save()
            logger.info("Logo uploaded for user %d — color: %s", request.user.id, hex_color)
            return Response(CompanyResponseSerializer(company).data)
            
        elif request.method == "DELETE":
            if company:
                company.logo_data = None
                company.primary_color = "#000000"
                company.save()
            return Response(CompanyResponseSerializer(company).data)


# -------------------------------------------------------------
# Employee Views
# -------------------------------------------------------------
class EmployeeViews:
    @staticmethod
    @api_view(["GET", "POST"])
    @permission_classes([IsAuthenticated])
    def employee_list_create(request):
        if request.method == "GET":
            page = int(request.GET.get("page", 1))
            per_page = int(request.GET.get("per_page", 20))
            search = request.GET.get("search")
            department = request.GET.get("department")
            res = employee_service.list_employees(None, request.user, page, per_page, search, department)
            return Response(EmployeeListResponseSerializer(res).data)
        elif request.method == "POST":
            employee_limit = get_employee_limit(request.user)
            active_employee_count = Employee.objects.filter(user=request.user, is_active=True).count()
            if employee_limit is not None and active_employee_count >= employee_limit:
                raise ForbiddenError(
                    f"Your current plan supports up to {employee_limit} active employees. "
                    "Upgrade your plan to add more employees."
                )
            serializer = EmployeeCreateSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            employee = employee_service.create_employee(None, request.user, serializer.validated_data)
            return Response(EmployeeResponseSerializer(employee).data, status=status.HTTP_201_CREATED)

    @staticmethod
    @api_view(["GET", "PUT", "DELETE"])
    @permission_classes([IsAuthenticated])
    def employee_detail(request, employee_id):
        if request.method == "GET":
            employee = employee_service.get_employee(None, request.user, employee_id)
            return Response(EmployeeResponseSerializer(employee).data)
        elif request.method == "PUT":
            serializer = EmployeeUpdateSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            employee = employee_service.update_employee(
                None, request.user, employee_id, serializer.validated_data
            )
            return Response(EmployeeResponseSerializer(employee).data)
        elif request.method == "DELETE":
            employee = employee_service.delete_employee(None, request.user, employee_id)
            return Response(EmployeeResponseSerializer(employee).data)


# -------------------------------------------------------------
# Salary Slip Views
# -------------------------------------------------------------
class SalarySlipViews:
    @staticmethod
    @api_view(["GET"])
    @permission_classes([IsAuthenticated])
    def salary_slip_list(request):
        page = int(request.GET.get("page", 1))
        per_page = int(request.GET.get("per_page", 20))
        month = request.GET.get("month")
        year = request.GET.get("year")
        employee_id = request.GET.get("employee_id")
        
        month_val = int(month) if month else None
        year_val = int(year) if year else None
        emp_id_val = int(employee_id) if employee_id else None
        
        res = salary_service.list_slips(None, request.user, page, per_page, month_val, year_val, emp_id_val)
        return Response(SalarySlipListResponseSerializer(res).data)

    @staticmethod
    @api_view(["POST"])
    @permission_classes([IsAuthenticated])
    def generate_slips(request):
        require_minimum_plan(request.user, PLAN_PROFESSIONAL, "Bulk salary slip generation")
        serializer = GenerateSlipsRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        month = serializer.validated_data["month"]
        year = serializer.validated_data["year"]
        slips = salary_service.generate_bulk_slips(None, request.user, month, year)
        return Response({"generated": len(slips), "month": month, "year": year}, status=status.HTTP_201_CREATED)

    @staticmethod
    @api_view(["POST"])
    @permission_classes([IsAuthenticated])
    def generate_single_slip(request, employee_id):
        serializer = GenerateSlipsRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        month = serializer.validated_data["month"]
        year = serializer.validated_data["year"]
        
        employee = employee_service.get_employee(None, request.user, employee_id)
        slip = salary_service.generate_slip_for_employee(None, request.user, employee, month, year)
        return Response(SalarySlipResponseSerializer(slip).data, status=status.HTTP_201_CREATED)

    @staticmethod
    @api_view(["GET"])
    @permission_classes([IsAuthenticated])
    def get_slip(request, slip_id):
        slip = salary_service.get_slip(None, request.user, slip_id)
        return Response(SalarySlipResponseSerializer(slip).data)

    @staticmethod
    @api_view(["GET"])
    @permission_classes([IsAuthenticated])
    def download_pdf(request, slip_id):
        include_doj = request.GET.get("include_doj", "true").lower() == "true"
        slip = salary_service.get_slip(None, request.user, slip_id)
        company = company_service.get_company(None, request.user)
        
        from app.services.pdf_service import generate_pdf_bytes, MONTH_NAMES
        pdf_bytes = generate_pdf_bytes(slip, company, include_doj=include_doj)
        
        emp_name = slip.employee.full_name.replace(" ", "_")
        month_name = MONTH_NAMES[slip.month] if 1 <= slip.month <= 12 else str(slip.month)
        filename = f"{emp_name}_SalarySlip_{month_name}{slip.year}.pdf"
        
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        response["X-Filename"] = filename
        return response

    @staticmethod
    @api_view(["POST"])
    @permission_classes([IsAuthenticated])
    def email_slip(request, slip_id):
        slip = salary_service.get_slip(None, request.user, slip_id)
        if not slip.employee.email:
            return Response({"sent": False, "message": "Employee has no email address configured."})
        if "@" not in slip.employee.email:
            return Response({"sent": False, "message": f"Invalid email address: {slip.employee.email}"})
            
        company = company_service.get_company(None, request.user)
        if not settings.EMAIL_HOST_USER or not settings.EMAIL_HOST_PASSWORD:
            return Response({
                "sent": False,
                "message": "SMTP not configured. Set SMTP_USER and SMTP_PASSWORD in backend/.env to enable email.",
            })
            
        from app.services.pdf_service import generate_pdf_bytes
        pdf_bytes = generate_pdf_bytes(slip, company)
        company_name = company.company_name if company else ""
        
        from app.services.email_service import send_salary_slip_email
        success = send_salary_slip_email(
            slip.employee.email,
            slip.employee.full_name,
            slip.month,
            slip.year,
            pdf_bytes,
            company_name,
        )
        if success:
            from app.models.salary_slip import SlipStatus
            from django.utils import timezone
            slip.status = SlipStatus.sent
            slip.emailed_at = timezone.now()
            slip.save()
            return Response({"sent": True, "message": f"Email sent to {slip.employee.email}"})
            
        return Response({
            "sent": False,
            "message": "Failed to send email. Verify SMTP credentials (Gmail requires App Password, not regular password).",
        })

    @staticmethod
    @api_view(["DELETE"])
    @permission_classes([IsAuthenticated])
    def delete_slip(request, slip_id):
        salary_service.delete_slip(None, request.user, slip_id)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @staticmethod
    @api_view(["GET", "DELETE"])
    @permission_classes([IsAuthenticated])
    def get_or_delete_slip(request, slip_id):
        if request.method == "GET":
            slip = salary_service.get_slip(None, request.user, slip_id)
            return Response(SalarySlipResponseSerializer(slip).data)
        elif request.method == "DELETE":
            salary_service.delete_slip(None, request.user, slip_id)
            return Response(status=status.HTTP_204_NO_CONTENT)


# -------------------------------------------------------------
# Attendance Views
# -------------------------------------------------------------
class AttendanceViews:
    @staticmethod
    @api_view(["POST"])
    @permission_classes([IsAuthenticated])
    def mark_attendance(request):
        require_minimum_plan(request.user, PLAN_PROFESSIONAL, "Attendance and leave tracking")
        serializer = AttendanceCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        res = attendance_service.mark_attendance(
            None,
            request.user,
            serializer.validated_data["employee_id"],
            serializer.validated_data["date"],
            serializer.validated_data["status"],
        )
        return Response(AttendanceResponseSerializer(res).data, status=status.HTTP_201_CREATED)

    @staticmethod
    @api_view(["POST"])
    @permission_classes([IsAuthenticated])
    def bulk_mark_leaves(request):
        require_minimum_plan(request.user, PLAN_PROFESSIONAL, "Attendance and leave tracking")
        serializer = AttendanceBulkCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        records = attendance_service.bulk_mark_leaves(
            None,
            request.user,
            serializer.validated_data["employee_id"],
            serializer.validated_data["month"],
            serializer.validated_data["year"],
            serializer.validated_data["leave_dates"],
            serializer.validated_data.get("weekoff_dates"),
        )
        return Response({"count": len(records), "employee_id": serializer.validated_data["employee_id"]}, status=status.HTTP_201_CREATED)

    @staticmethod
    @api_view(["GET"])
    @permission_classes([IsAuthenticated])
    def get_monthly_attendance(request):
        require_minimum_plan(request.user, PLAN_PROFESSIONAL, "Attendance and leave tracking")
        emp_id = request.GET.get("employee_id")
        month = request.GET.get("month")
        year = request.GET.get("year")
        if not emp_id or not month or not year:
            raise BadRequestError("employee_id, month, and year are required query params")
            
        records = attendance_service.get_monthly_attendance(
            None, request.user, int(emp_id), int(month), int(year)
        )
        return Response(AttendanceResponseSerializer(records, many=True).data)

    @staticmethod
    @api_view(["GET"])
    @permission_classes([IsAuthenticated])
    def get_leave_summary(request):
        require_minimum_plan(request.user, PLAN_ENTERPRISE, "Advanced attendance summaries")
        month = request.GET.get("month")
        year = request.GET.get("year")
        if not month or not year:
            raise BadRequestError("month and year are required query params")
            
        res = attendance_service.get_all_employees_leave_summary(
            None, request.user, int(month), int(year)
        )
        return Response(EmployeeLeavesSummarySerializer(res, many=True).data)


# -------------------------------------------------------------
# Dashboard Views
# -------------------------------------------------------------
class DashboardViews:
    @staticmethod
    @api_view(["GET"])
    @permission_classes([IsAuthenticated])
    def get_stats(request):
        require_minimum_plan(request.user, PLAN_STARTER, "Dashboard overview")
        res = dashboard_service.get_dashboard_stats(None, request.user)
        return Response(DashboardStatsSerializer(res).data)

    @staticmethod
    @api_view(["GET"])
    @permission_classes([IsAuthenticated])
    def get_payroll_summary(request):
        require_minimum_plan(request.user, PLAN_PROFESSIONAL, "Payroll dashboard and reports")
        month = request.GET.get("month", datetime.now().month)
        year = request.GET.get("year", datetime.now().year)
        res = dashboard_service.get_payroll_summary(None, request.user, int(month), int(year))
        return Response(PayrollSummarySerializer(res).data)

    @staticmethod
    @api_view(["GET"])
    @permission_classes([IsAuthenticated])
    def get_department_breakdown(request):
        require_minimum_plan(request.user, PLAN_ENTERPRISE, "Department-wise payroll insights")
        res = dashboard_service.get_department_breakdown(None, request.user)
        return Response(DepartmentBreakdownSerializer(res, many=True).data)


# -------------------------------------------------------------
# Admin Views
# -------------------------------------------------------------
class AdminViews:
    @staticmethod
    @api_view(["GET"])
    @permission_classes([IsAdmin])
    def list_users(request):
        require_minimum_plan(request.user, PLAN_ENTERPRISE, "User and account administration")
        page = int(request.GET.get("page", 1))
        per_page = int(request.GET.get("per_page", 20))
        res = admin_service.list_users(None, page, per_page)
        # Render lists inside container dict
        items_serialized = UserAdminResponseSerializer(res["items"], many=True).data
        return Response({
            "items": items_serialized,
            "total": res["total"],
            "page": res["page"],
            "per_page": res["per_page"],
            "pages": res["pages"],
        })

    @staticmethod
    @api_view(["PUT", "DELETE"])
    @permission_classes([IsAdmin])
    def update_or_delete_user(request, user_id):
        require_minimum_plan(request.user, PLAN_ENTERPRISE, "User and account administration")
        if request.method == "PUT":
            serializer = UpdateUserRoleRequestSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            user = admin_service.update_user(
                None,
                user_id,
                serializer.validated_data.get("role"),
                serializer.validated_data.get("is_active"),
            )
            return Response(UserAdminResponseSerializer(user).data)
        elif request.method == "DELETE":
            user = admin_service.deactivate_user(None, user_id)
            return Response(UserAdminResponseSerializer(user).data)

    @staticmethod
    @api_view(["GET"])
    @permission_classes([IsAdmin])
    def platform_stats(request):
        require_minimum_plan(request.user, PLAN_ENTERPRISE, "User and account administration")
        res = admin_service.get_platform_stats(None)
        return Response(PlatformStatsSerializer(res).data)


# -------------------------------------------------------------
# Payment Views
# -------------------------------------------------------------
class PaymentViews:
    @staticmethod
    @api_view(["POST"])
    @permission_classes([IsAuthenticated])
    def create_order(request):
        from app.serializers.payment import CreatePaymentOrderSerializer
        from app.services import payment_service
        serializer = CreatePaymentOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        res = payment_service.create_order(request.user, serializer.validated_data["plan_name"])
        return Response({
            "razorpay_key_id": res["razorpay_key_id"],
            "order_id": res["razorpay_order"]["id"],
            "amount": res["razorpay_order"]["amount"],
            "currency": res["razorpay_order"]["currency"],
            "plan_name": res["payment_order"].plan_name,
        })

    @staticmethod
    @api_view(["POST"])
    @permission_classes([IsAuthenticated])
    def verify_payment(request):
        from app.serializers.payment import VerifyPaymentSerializer
        from app.services import payment_service
        serializer = VerifyPaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        res = payment_service.verify_payment(
            request.user,
            serializer.validated_data["razorpay_order_id"],
            serializer.validated_data["razorpay_payment_id"],
            serializer.validated_data["razorpay_signature"],
        )
        return Response(res)

    @staticmethod
    @api_view(["GET"])
    @permission_classes([IsAuthenticated])
    def payment_history(request):
        from app.serializers.payment import PaymentOrderResponseSerializer
        from app.services import payment_service
        orders = payment_service.get_user_payment_history(request.user)
        return Response({
            "current_plan": getattr(request.user, "plan", "starter"),
            "orders": PaymentOrderResponseSerializer(orders, many=True).data
        })


@api_view(["GET"])
def health_check(request):
    return Response({"status": "healthy", "app": settings.APP_NAME})


@api_view(["GET"])
def root_view(request):
    return Response({
        "message": "Employee Salary Slip API is running.",
        "health_check": "/api/v1/health"
    })
