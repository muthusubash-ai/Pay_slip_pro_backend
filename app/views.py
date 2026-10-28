import base64
import calendar
import io
import logging
import re
from collections import Counter
from datetime import date, datetime, timezone

import httpx
from django.conf import settings
from django.http import HttpResponse
from django.middleware.csrf import get_token
from django.shortcuts import redirect
from django.views.decorators.csrf import csrf_protect
from PIL import Image as PILImage
from PIL import ImageOps
from rest_framework import status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    parser_classes,
    permission_classes,
    throttle_classes,
)
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


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
    with PILImage.open(io.BytesIO(image_bytes)) as source:
        img = ImageOps.exif_transpose(source).copy()

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
from app.auth.cookies import clear_auth_cookies, set_auth_cookies
from app.auth.throttles import (
    IfscLookupRateThrottle,
    LocationLookupRateThrottle,
    LoginAccountRateThrottle,
    LoginIPRateThrottle,
    LogoUploadRateThrottle,
    EmailSlipRateThrottle,
    RegisterIPRateThrottle,
    RegisterAccountRateThrottle,
    PasswordResetRequestAccountRateThrottle,
    PasswordResetRequestIPRateThrottle,
    PasswordResetVerifyAccountRateThrottle,
    PasswordResetVerifyIPRateThrottle,
    AIAssistantRateThrottle,
)
from app.exceptions import BadRequestError, ForbiddenError
from app.models.employee import Employee
from app.models.salary_slip import SalarySlip
from app.models.user import User
from app.plans import (
    PLAN_ENTERPRISE,
    PLAN_PROFESSIONAL,
    PLAN_STARTER,
    get_employee_limit,
    require_minimum_plan,
)
from app.serializers.admin import (
    PlatformStatsSerializer,
    UpdateUserRoleRequestSerializer,
    UserAdminResponseSerializer,
)
from app.serializers.attendance import (
    AttendanceBulkCreateSerializer,
    AttendanceCreateSerializer,
    AttendanceResponseSerializer,
    EmployeeLeavesSummarySerializer,
)
from app.serializers.auth import (
    ForgotPasswordRequestSerializer,
    RefreshRequestSerializer,
    RegisterRequestSerializer,
    ResetPasswordRequestSerializer,
    UpdateProfileRequestSerializer,
    UserResponseSerializer,
)
from app.serializers.company import (
    CompanyResponseSerializer,
    CompanyUpdateSerializer,
)
from app.serializers.dashboard import (
    DashboardStatsSerializer,
    DepartmentBreakdownSerializer,
    PayrollSummarySerializer,
)
from app.serializers.employee import (
    EmployeeCreateSerializer,
    EmployeeListResponseSerializer,
    EmployeeResponseSerializer,
    EmployeeUpdateSerializer,
)
from app.serializers.salary_slip import (
    GenerateSlipsRequestSerializer,
    SalarySlipListResponseSerializer,
    SalarySlipResponseSerializer,
)
from app.services import (
    admin_service,
    attendance_service,
    auth_service,
    company_service,
    dashboard_service,
    employee_service,
    salary_service,
)
from app.services.bank_lookup import lookup_ifsc
from app.services.location_lookup import lookup_indian_pin, suggest_addresses, suggest_cities
from app.services.ai_assistant_service import ask_assistant
from app.serializers.ai_assistant import AIAssistantChatRequestSerializer, AIAssistantChatResponseSerializer
from app.upload_validation import validate_logo_upload

logger = logging.getLogger(__name__)


def resolve_frontend_url(request):
    origin = request.headers.get("Origin") or ""
    if origin and (origin.startswith("http://") or origin.startswith("https://")):
        return origin.rstrip('/')
    referer = request.headers.get("Referer") or ""
    if referer and (referer.startswith("http://") or referer.startswith("https://")):
        from urllib.parse import urlparse
        p = urlparse(referer)
        if p.scheme and p.netloc:
            return f"{p.scheme}://{p.netloc}".rstrip('/')
    if hasattr(request, "get_host") and request.get_host():
        scheme = "https" if (request.is_secure() or request.headers.get("X-Forwarded-Proto") == "https") else "http"
        return f"{scheme}://{request.get_host()}".rstrip('/')
    return getattr(settings, 'FRONTEND_URL', 'https://payslippro.sbs').rstrip('/')


def resolve_target_user(request):
    """
    If request.user is a platform admin (or role == admin), allow scoping to a target
    company user provided via query params ('company_user_id'), custom header ('X-Company-User-Id'),
    or request payload. Otherwise, strictly return request.user.
    This guarantees non-admin users cannot access or view other companies' data.
    """
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return user

    is_admin = (
        bool(getattr(user, "is_platform_admin", False))
        or bool(getattr(user, "is_superuser", False))
        or bool(getattr(user, "is_staff", False))
        or str(getattr(user, "role", "")).strip().lower() in ("admin", "administrator")
    )

    if is_admin:
        target_id = None
        # 1. DRF query params
        if hasattr(request, "query_params") and request.query_params.get("company_user_id"):
            target_id = request.query_params.get("company_user_id")
        # 2. Django GET query dict
        elif hasattr(request, "GET") and request.GET.get("company_user_id"):
            target_id = request.GET.get("company_user_id")
        # 3. Request headers
        elif hasattr(request, "headers"):
            target_id = (
                request.headers.get("X-Company-User-Id")
                or request.headers.get("x-company-user-id")
                or request.headers.get("company-user-id")
            )
        # 4. WSGI META headers
        if not target_id and hasattr(request, "META"):
            target_id = request.META.get("HTTP_X_COMPANY_USER_ID") or request.META.get("HTTP_COMPANY_USER_ID")
        # 5. POST/PUT request body
        if not target_id and hasattr(request, "data") and isinstance(request.data, dict):
            target_id = request.data.get("company_user_id")

        if target_id is not None:
            clean_str = str(target_id).strip()
            if clean_str and clean_str.lower() not in ("null", "undefined", "none", "0", ""):
                try:
                    uid = int(clean_str)
                    target_user = User.objects.filter(id=uid).first()
                    if target_user:
                        logger.info(
                            "resolve_target_user: Scoped admin '%s' to company user '%s' (id: %d)",
                            user.email,
                            target_user.email,
                            uid,
                        )
                        return target_user
                    else:
                        logger.warning(
                            "resolve_target_user: Admin '%s' requested unknown company user id: %d",
                            user.email,
                            uid,
                        )
                except (ValueError, TypeError) as ex:
                    logger.warning("resolve_target_user: Invalid target_id %r: %s", target_id, ex)

    return user


@api_view(["GET"])
@permission_classes([IsAuthenticated])
@throttle_classes([IfscLookupRateThrottle])
def ifsc_lookup(request):
    code = str(request.query_params.get("code", "")).strip().upper()
    if not re.fullmatch(r"[A-Z]{4}0[A-Z0-9]{6}", code):
        return Response({"detail": "Enter a valid 11-character IFSC code."}, status=status.HTTP_400_BAD_REQUEST)
    try:
        details = lookup_ifsc(code)
    except (httpx.HTTPError, ValueError):
        logger.warning("IFSC lookup unavailable for %s", code)
        return Response({"detail": "Branch lookup is temporarily unavailable. Try again shortly."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    if details is None:
        return Response({"detail": "No branch found for this IFSC code."}, status=status.HTTP_404_NOT_FOUND)
    return Response(details)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
@throttle_classes([LocationLookupRateThrottle])
def address_suggestions(request):
    query = str(request.query_params.get("q", "")).strip()
    if len(query) < 4 or len(query) > 120:
        return Response({"detail": "Enter 4-120 characters to search for an address."}, status=status.HTTP_400_BAD_REQUEST)
    try:
        suggestions = suggest_addresses(query)
    except (httpx.HTTPError, TypeError, ValueError):
        logger.warning("Address suggestions unavailable")
        return Response({"detail": "Address suggestions are temporarily unavailable."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    return Response({"items": suggestions})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
@throttle_classes([LocationLookupRateThrottle])
def city_suggestions(request):
    query = str(request.query_params.get("q", "")).strip()
    state = str(request.query_params.get("state", "")).strip()
    if not (2 <= len(query) <= 80 and 2 <= len(state) <= 100):
        return Response({"detail": "Enter a state and at least 2 city characters."}, status=status.HTTP_400_BAD_REQUEST)
    try:
        cities = suggest_cities(query, state)
    except (httpx.HTTPError, TypeError, ValueError):
        logger.warning("City suggestions unavailable")
        return Response({"detail": "City suggestions are temporarily unavailable."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    return Response({"items": cities})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
@throttle_classes([LocationLookupRateThrottle])
def pin_lookup(request):
    code = str(request.query_params.get("code", "")).strip()
    if not re.fullmatch(r"\d{6}", code):
        return Response({"detail": "Enter a valid 6-digit Indian PIN code."}, status=status.HTTP_400_BAD_REQUEST)
    try:
        details = lookup_indian_pin(code)
    except (httpx.HTTPError, TypeError, ValueError):
        logger.warning("PIN lookup unavailable for %s", code)
        return Response({"detail": "PIN lookup is temporarily unavailable."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    if details is None:
        return Response({"detail": "No area found for this PIN code."}, status=status.HTTP_404_NOT_FOUND)
    return Response(details)


# -------------------------------------------------------------
# Auth Views
# -------------------------------------------------------------
class AuthViews:
    @staticmethod
    @csrf_protect
    @api_view(["POST"])
    @authentication_classes([])
    @permission_classes([AllowAny])
    @throttle_classes([RegisterIPRateThrottle, RegisterAccountRateThrottle])
    def register(request):
        serializer = RegisterRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = auth_service.register_user(
            None,
            serializer.validated_data["email"],
            serializer.validated_data["password"],
            serializer.validated_data["full_name"],
            serializer.validated_data.get("phone", ""),
        )
        return Response(UserResponseSerializer(user).data, status=status.HTTP_201_CREATED)

    @staticmethod
    @csrf_protect
    @api_view(["POST"])
    @authentication_classes([])
    @permission_classes([AllowAny])
    @throttle_classes([LoginIPRateThrottle, LoginAccountRateThrottle])
    def login(request):
        # Support both form-data (from OAuth2PasswordRequestForm) and raw JSON
        username = (request.data.get("username") or request.data.get("email") or "").strip().lower()
        password = request.data.get("password")
        if not username or not password:
            raise BadRequestError("Username and password are required")
        res = auth_service.authenticate_user(None, username, password)
        response = Response({"message": "Login successful"})
        set_auth_cookies(response, res)
        get_token(request)
        return response

    @staticmethod
    @csrf_protect
    @api_view(["POST"])
    @authentication_classes([])
    @permission_classes([AllowAny])
    def refresh(request):
        refresh_token = request.COOKIES.get(settings.AUTH_REFRESH_COOKIE_NAME)
        if not refresh_token:
            serializer = RefreshRequestSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            refresh_token = serializer.validated_data["refresh_token"]
        tokens = auth_service.refresh_tokens(None, refresh_token)
        response = Response({"message": "Session refreshed"})
        set_auth_cookies(response, tokens)
        return response

    @staticmethod
    @csrf_protect
    @api_view(["POST"])
    @authentication_classes([])
    @permission_classes([AllowAny])
    def logout(request):
        refresh_token = request.COOKIES.get(settings.AUTH_REFRESH_COOKIE_NAME)
        if not refresh_token and request.data.get("refresh_token"):
            serializer = RefreshRequestSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            refresh_token = serializer.validated_data["refresh_token"]
        if refresh_token:
            auth_service.logout_user(None, refresh_token)
        response = Response(status=status.HTTP_204_NO_CONTENT)
        clear_auth_cookies(response)
        return response

    @staticmethod
    @api_view(["GET"])
    @authentication_classes([])
    @permission_classes([AllowAny])
    def csrf(request):
        return Response({"csrf_token": get_token(request)})

    @staticmethod
    @api_view(["GET", "PUT"])
    @permission_classes([IsAuthenticated])
    def me(request):
        if request.method == "GET":
            request.user.check_and_update_plan_expiry()
            return Response(UserResponseSerializer(request.user).data)
        elif request.method == "PUT":
            serializer = UpdateProfileRequestSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            full_name = serializer.validated_data.get("full_name")
            phone = serializer.validated_data.get("phone")
            notification_email = serializer.validated_data.get("notification_email")
            if full_name is not None or phone is not None or notification_email is not None:
                user = auth_service.update_profile(
                    None,
                    request.user,
                    full_name=full_name,
                    phone=phone,
                    notification_email=notification_email,
                )
            else:
                user = request.user
            company_name = serializer.validated_data.get("company_name")
            if company_name is not None and company_name.strip():
                company_service.update_company(None, user, {"company_name": company_name.strip()})
                user.refresh_from_db()
            return Response(UserResponseSerializer(user).data)

    @staticmethod
    @csrf_protect
    @api_view(["POST"])
    @authentication_classes([])
    @permission_classes([AllowAny])
    @throttle_classes([
        PasswordResetRequestIPRateThrottle,
        PasswordResetRequestAccountRateThrottle,
    ])
    def forgot_password(request):
        serializer = ForgotPasswordRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"].strip().lower()

        from app.models.user import User
        if not User.objects.filter(email__iexact=email).exists():
            return Response(
                {"detail": "This email is not registered. Please register first.", "sent": False},
                status=status.HTTP_400_BAD_REQUEST,
            )

        code = auth_service.generate_reset_code(None, email)
        if code:
            from app.services.email_service import send_password_reset_email
            sent = send_password_reset_email(email, code)
            if sent:
                return Response({"message": "Reset code sent to your email. Check your inbox.", "sent": True})
            return Response(
                {"detail": "Failed to send email. Check SMTP settings.", "sent": False},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        return Response(
            {"detail": "This email is not registered. Please register first.", "sent": False},
            status=status.HTTP_400_BAD_REQUEST,
        )

    @staticmethod
    @csrf_protect
    @api_view(["POST"])
    @authentication_classes([])
    @permission_classes([AllowAny])
    @throttle_classes([
        PasswordResetVerifyIPRateThrottle,
        PasswordResetVerifyAccountRateThrottle,
    ])
    def reset_password(request):
        serializer = ResetPasswordRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        auth_service.reset_password_with_code(
            None,
            serializer.validated_data["email"].strip().lower(),
            serializer.validated_data["token"].strip(),
            serializer.validated_data["new_password"],
        )
        return Response({"message": "Password reset successful. You can now login with your new password."})

    @staticmethod
    @api_view(["GET"])
    @authentication_classes([])
    @permission_classes([AllowAny])
    def google_login(request):
        from app.services.google_auth_service import create_google_login_request

        url, oauth_state = create_google_login_request()
        response = redirect(url)
        response.set_cookie(
            settings.GOOGLE_OAUTH_STATE_COOKIE_NAME,
            oauth_state,
            max_age=settings.GOOGLE_OAUTH_STATE_TTL_SECONDS,
            path="/api/v1/auth/google/",
            httponly=True,
            secure=settings.AUTH_COOKIE_SECURE,
            samesite="Lax",
            domain=settings.AUTH_COOKIE_DOMAIN,
        )
        return response

    @staticmethod
    @api_view(["GET"])
    @authentication_classes([])
    @permission_classes([AllowAny])
    def google_callback(request):
        from app.services.google_auth_service import (
            consume_google_oauth_state,
            exchange_code_for_tokens,
            generate_tokens_for_user,
            get_google_user_info,
            get_or_create_google_user,
        )
        code = request.GET.get("code")
        oauth_state = request.GET.get("state", "")
        cookie_state = request.COOKIES.get(settings.GOOGLE_OAUTH_STATE_COOKIE_NAME, "")
        if request.GET.get("error") or not code:
            raise BadRequestError("Google authentication was cancelled or denied")
        code_verifier = consume_google_oauth_state(oauth_state, cookie_state)
        # Run async actions inside sync view
        import asyncio
        google_tokens = asyncio.run(exchange_code_for_tokens(code, code_verifier))
        google_user = asyncio.run(get_google_user_info(google_tokens["access_token"]))
        
        user = get_or_create_google_user(None, google_user)
        tokens = generate_tokens_for_user(None, user)
        
        response = redirect(f"{settings.FRONTEND_URL.rstrip('/')}/auth/google/callback")
        set_auth_cookies(response, tokens)
        response.delete_cookie(
            settings.GOOGLE_OAUTH_STATE_COOKIE_NAME,
            path="/api/v1/auth/google/",
            domain=settings.AUTH_COOKIE_DOMAIN,
            samesite="Lax",
        )
        get_token(request)
        return response


# -------------------------------------------------------------
# Company Views
# -------------------------------------------------------------
class CompanyViews:
    @staticmethod
    @api_view(["GET", "PUT"])
    @permission_classes([IsAuthenticated])
    def company_detail(request):
        effective_user = resolve_target_user(request)
        company = company_service.get_company(None, effective_user)
        if request.method == "GET":
            if not company:
                from app.models.company import Company
                company = Company.objects.create(
                    user=effective_user,
                    company_name="My Company"
                )
            return Response(CompanyResponseSerializer(company, context={"request": request}).data)
        elif request.method == "PUT":
            require_minimum_plan(request.user, PLAN_PROFESSIONAL, "Company settings and branding")
            logger.info("Company PUT request data: %s", request.data)
            serializer = CompanyUpdateSerializer(data=request.data)
            if not serializer.is_valid():
                logger.error("Company validation failed: %s", serializer.errors)
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
            company = company_service.update_company(None, effective_user, serializer.validated_data)
            logger.info("Company successfully updated: %s", company.company_name)
            return Response(CompanyResponseSerializer(company, context={"request": request}).data)

    @staticmethod
    @api_view(["POST", "DELETE"])
    @permission_classes([IsAuthenticated])
    @parser_classes([MultiPartParser, FormParser])
    @throttle_classes([LogoUploadRateThrottle])
    def company_logo(request):
        require_minimum_plan(request.user, PLAN_PROFESSIONAL, "Custom company branding")
        effective_user = resolve_target_user(request)
        company = company_service.get_company(None, effective_user)
        if request.method == "POST":
            file_obj = request.FILES.get("file")
            if not file_obj:
                raise BadRequestError("No logo file uploaded")
            
            contents = validate_logo_upload(file_obj)
            logo_data, hex_color = _process_logo(contents)
            
            if not company:
                from app.models.company import Company
                company = Company(user=effective_user, company_name="My Company")
                company.save()
                
            company.logo_data = logo_data
            company.primary_color = hex_color
            company.save()
            logger.info("Logo uploaded for user %d — color: %s", effective_user.id, hex_color)
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
        effective_user = resolve_target_user(request)
        if request.method == "GET":
            page = int(request.GET.get("page", 1))
            per_page = int(request.GET.get("per_page", 20))
            search = request.GET.get("search")
            department = request.GET.get("department")
            sort_by = request.GET.get("sort") or request.GET.get("sort_by")
            status_param = request.GET.get("status", "active")
            res = employee_service.list_employees(None, effective_user, page, per_page, search, department, sort_by=sort_by, status=status_param)
            return Response(EmployeeListResponseSerializer(res).data)
        elif request.method == "POST":
            employee_limit = get_employee_limit(effective_user)
            active_employee_count = Employee.objects.filter(user=effective_user, is_active=True).count()
            if employee_limit is not None and active_employee_count >= employee_limit:
                raise ForbiddenError(
                    f"Your current plan supports up to {employee_limit} active employees. "
                    "Upgrade your plan to add more employees."
                )
            send_invitation = bool(request.data.get("send_invitation", False))
            serializer = EmployeeCreateSerializer(data=request.data, context={"request": request})
            serializer.is_valid(raise_exception=True)
            employee = employee_service.create_employee(None, effective_user, serializer.validated_data)

            try:
                from app.services.email_service import send_employee_added_notice_email
                send_employee_added_notice_email(
                    to_email=effective_user.effective_notification_email,
                    employee_name=employee.full_name,
                    employee_code=employee.employee_code,
                    designation=employee.designation or "",
                    company_name=effective_user.company_name,
                )
            except Exception:
                logging.getLogger(__name__).warning("Employee-added HR notice failed for user %s", effective_user.pk, exc_info=True)

            email_sent = False
            if send_invitation and employee.email:
                try:
                    from app.services.email_service import send_employee_registration_invitation_email
                    frontend_url = resolve_frontend_url(request)
                    from attendance.security import issue_invite
                    invitation_token = issue_invite(employee)
                    portal_url = f"{frontend_url}/biometric"
                    company_name = getattr(effective_user, 'company_name', '') or getattr(effective_user, 'company', '') or settings.APP_NAME
                    email_sent = send_employee_registration_invitation_email(
                        to_email=employee.email,
                        employee_name=employee.full_name,
                        employee_code=employee.employee_code,
                        portal_url=portal_url,
                        company_name=company_name,
                        invitation_token=invitation_token,
                    )
                except Exception as ex:
                    logger.warning("Failed to send onboarding email to %s: %s", employee.email, ex)

            data = EmployeeResponseSerializer(employee).data
            data["email_sent"] = email_sent
            return Response(data, status=status.HTTP_201_CREATED)

    @staticmethod
    @api_view(["GET", "PUT", "DELETE"])
    @permission_classes([IsAuthenticated])
    def employee_detail(request, employee_id):
        effective_user = resolve_target_user(request)
        if request.method == "GET":
            employee = employee_service.get_employee(None, effective_user, employee_id)
            return Response(EmployeeResponseSerializer(employee).data)
        elif request.method == "PUT":
            employee = employee_service.get_employee(None, effective_user, employee_id)
            serializer = EmployeeUpdateSerializer(instance=employee, data=request.data, context={"request": request})
            serializer.is_valid(raise_exception=True)
            employee = employee_service.update_employee(
                None, effective_user, employee_id, serializer.validated_data
            )
            return Response(EmployeeResponseSerializer(employee).data)
        elif request.method == "DELETE":
            res = employee_service.delete_employee(None, effective_user, employee_id)
            return Response(
                {
                    "detail": f"Employee {res.get('full_name', '')} ({res.get('employee_code', '')}) has been deactivated and removed successfully.",
                    "id": employee_id,
                    "employee_code": res.get("employee_code"),
                    "full_name": res.get("full_name"),
                    "email": res.get("email"),
                    "is_active": False,
                },
                status=status.HTTP_200_OK
            )

    @staticmethod
    @api_view(["POST"])
    @permission_classes([IsAuthenticated])
    def send_invite(request, employee_id):
        effective_user = resolve_target_user(request)
        employee = employee_service.get_employee(None, effective_user, employee_id)
        if not employee.email:
            return Response({"detail": "Employee has no email address configured."}, status=status.HTTP_400_BAD_REQUEST)

        from app.services.email_service import send_employee_registration_invitation_email
        frontend_url = resolve_frontend_url(request)
        from attendance.security import issue_invite
        invitation_token = issue_invite(employee)
        portal_url = f"{frontend_url}/biometric"
        import urllib.parse
        registration_url = f"{portal_url}?tab=onboard&invite={urllib.parse.quote(invitation_token)}#invite={urllib.parse.quote(invitation_token)}"
        company_name = getattr(effective_user, 'company_name', '') or getattr(effective_user, 'company', '') or settings.APP_NAME

        success = send_employee_registration_invitation_email(
            to_email=employee.email,
            employee_name=employee.full_name,
            employee_code=employee.employee_code,
            portal_url=portal_url,
            company_name=company_name,
            invitation_token=invitation_token,
        )
        msg = (
            f"Registration invitation email sent to {employee.email} successfully."
            if success
            else "Invite link generated successfully (email delivery could not be verified, but you can copy the link directly)."
        )
        return Response({
            "detail": msg,
            "email_sent": success,
            "invite_url": registration_url,
            "token": invitation_token
        }, status=status.HTTP_200_OK)

    @staticmethod
    @api_view(["POST"])
    @permission_classes([IsAuthenticated])
    def reactivate_employee(request, employee_id):
        effective_user = resolve_target_user(request)
        new_email = request.data.get("email")
        employee = employee_service.reactivate_employee(None, effective_user, employee_id, new_email=new_email)
        return Response(EmployeeResponseSerializer(employee).data, status=status.HTTP_200_OK)

    @staticmethod
    @api_view(["DELETE"])
    @permission_classes([IsAuthenticated])
    def permanent_delete_employee(request, employee_id):
        effective_user = resolve_target_user(request)
        res = employee_service.permanent_delete_employee(None, effective_user, employee_id)
        return Response(
            {
                "detail": f"Employee {res.get('full_name', '')} ({res.get('employee_code', '')}) and all of their records have been permanently deleted.",
                "id": employee_id,
            },
            status=status.HTTP_200_OK,
        )


# -------------------------------------------------------------
# Salary Slip Views
# -------------------------------------------------------------
class SalarySlipViews:
    @staticmethod
    @api_view(["GET"])
    @permission_classes([IsAuthenticated])
    def salary_slip_list(request):
        effective_user = resolve_target_user(request)
        page = int(request.GET.get("page", 1))
        per_page = int(request.GET.get("per_page", 20))
        month = request.GET.get("month")
        year = request.GET.get("year")
        employee_id = request.GET.get("employee_id")
        
        month_val = int(month) if month else None
        year_val = int(year) if year else None
        emp_id_val = int(employee_id) if employee_id else None
        
        res = salary_service.list_slips(None, effective_user, page, per_page, month_val, year_val, emp_id_val)
        return Response(SalarySlipListResponseSerializer(res).data)

    @staticmethod
    @api_view(["POST"])
    @permission_classes([IsAuthenticated])
    def generate_slips(request):
        require_minimum_plan(request.user, PLAN_PROFESSIONAL, "Bulk salary slip generation")
        effective_user = resolve_target_user(request)
        serializer = GenerateSlipsRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        month = serializer.validated_data["month"]
        year = serializer.validated_data["year"]
        slips = salary_service.generate_bulk_slips(None, effective_user, month, year)
        if slips:
            try:
                from app.services.email_service import send_slip_generation_summary_email
                send_slip_generation_summary_email(
                    to_email=effective_user.effective_notification_email,
                    count=len(slips),
                    month_name=calendar.month_name[month],
                    year=year,
                    company_name=effective_user.company_name,
                )
            except Exception:
                logging.getLogger(__name__).warning("Slip-generation summary email failed for user %s", effective_user.pk, exc_info=True)
        attendance_pending = [
            item["employee_id"]
            for item in attendance_service.get_attendance_readiness(effective_user, month, year)
            if not item["complete"] and not SalarySlip.objects.filter(
                user=effective_user, employee_id=item["employee_id"], month=month, year=year
            ).exists() and Employee.objects.filter(
                user=effective_user,
                id=item["employee_id"],
                date_of_joining__lte=date(year, month, calendar.monthrange(year, month)[1]),
            ).exists()
        ]
        msg = None
        if attendance_pending:
            msg = f"Save complete attendance for {month}/{year} before generating slips for {len(attendance_pending)} remaining employee(s)."
        elif len(slips) == 0:
            msg = f"Salary slips for all employees have already been generated for {month}/{year}. If you want to re-generate, you must delete the existing salary slip first."
        return Response({
            "generated": len(slips),
            "month": month,
            "year": year,
            "message": msg,
            "attendance_pending_employee_ids": attendance_pending,
        }, status=status.HTTP_201_CREATED)

    @staticmethod
    @api_view(["POST"])
    @permission_classes([IsAuthenticated])
    def generate_single_slip(request, employee_id):
        effective_user = resolve_target_user(request)
        serializer = GenerateSlipsRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        month = serializer.validated_data["month"]
        year = serializer.validated_data["year"]
        
        employee = employee_service.get_employee(None, effective_user, employee_id)
        slip = salary_service.generate_slip_for_employee(None, effective_user, employee, month, year)
        try:
            from app.services.email_service import send_slip_generated_email
            send_slip_generated_email(
                to_email=effective_user.effective_notification_email,
                employee_name=employee.full_name,
                month_name=calendar.month_name[month],
                year=year,
                company_name=effective_user.company_name,
            )
        except Exception:
            logging.getLogger(__name__).warning("Slip-generated email failed for user %s", effective_user.pk, exc_info=True)
        return Response(SalarySlipResponseSerializer(slip).data, status=status.HTTP_201_CREATED)

    @staticmethod
    @api_view(["GET"])
    @permission_classes([IsAuthenticated])
    def get_slip(request, slip_id):
        effective_user = resolve_target_user(request)
        slip = salary_service.get_slip(None, effective_user, slip_id)
        return Response(SalarySlipResponseSerializer(slip).data)

    @staticmethod
    @api_view(["GET"])
    @permission_classes([IsAuthenticated])
    def download_pdf(request, slip_id):
        effective_user = resolve_target_user(request)
        include_doj = request.GET.get("include_doj", "true").lower() == "true"
        slip = salary_service.get_slip(None, effective_user, slip_id)
        company = company_service.get_company(None, effective_user)
        
        from app.services.pdf_service import MONTH_NAMES, generate_pdf_bytes
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
    @throttle_classes([EmailSlipRateThrottle])
    def email_slip(request, slip_id):
        effective_user = resolve_target_user(request)
        slip = salary_service.get_slip(None, effective_user, slip_id)
        if not slip.employee.email:
            return Response({"sent": False, "message": "Employee has no email address configured."})
        if "@" not in slip.employee.email:
            return Response({"sent": False, "message": f"Invalid email address: {slip.employee.email}"})
            
        company = company_service.get_company(None, effective_user)
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
            from django.utils import timezone

            from app.models.salary_slip import SlipStatus
            slip.status = SlipStatus.sent
            slip.emailed_at = timezone.now()
            slip.save()
            try:
                from app.services.email_service import send_slip_emailed_notice_email
                send_slip_emailed_notice_email(
                    to_email=effective_user.effective_notification_email,
                    employee_name=slip.employee.full_name,
                    month_name=calendar.month_name[slip.month],
                    year=slip.year,
                    company_name=company_name,
                )
            except Exception:
                logging.getLogger(__name__).warning("Slip-emailed HR notice failed for user %s", effective_user.pk, exc_info=True)
            return Response({"sent": True, "message": f"Email sent to {slip.employee.email}"})
            
        return Response({
            "sent": False,
            "message": "Failed to send email. Verify SMTP credentials (Gmail requires App Password, not regular password).",
        })

    @staticmethod
    @api_view(["DELETE"])
    @permission_classes([IsAuthenticated])
    def delete_slip(request, slip_id):
        effective_user = resolve_target_user(request)
        salary_service.delete_slip(None, effective_user, slip_id)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @staticmethod
    @api_view(["GET", "DELETE"])
    @permission_classes([IsAuthenticated])
    def get_or_delete_slip(request, slip_id):
        effective_user = resolve_target_user(request)
        if request.method == "GET":
            slip = salary_service.get_slip(None, effective_user, slip_id)
            return Response(SalarySlipResponseSerializer(slip).data)
        elif request.method == "DELETE":
            salary_service.delete_slip(None, effective_user, slip_id)
            return Response(status=status.HTTP_204_NO_CONTENT)


# -------------------------------------------------------------
# Attendance Views
# -------------------------------------------------------------
class AttendanceViews:
    @staticmethod
    @api_view(["POST"])
    @permission_classes([IsAuthenticated])
    def mark_attendance(request):
        effective_user = resolve_target_user(request)
        serializer = AttendanceCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        res = attendance_service.mark_attendance(
            None,
            effective_user,
            serializer.validated_data["employee_id"],
            serializer.validated_data["date"],
            serializer.validated_data["status"],
        )
        return Response(AttendanceResponseSerializer(res).data, status=status.HTTP_201_CREATED)

    @staticmethod
    @api_view(["POST"])
    @permission_classes([IsAuthenticated])
    def bulk_mark_leaves(request):
        effective_user = resolve_target_user(request)
        serializer = AttendanceBulkCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        records = attendance_service.bulk_mark_leaves(
            None,
            effective_user,
            serializer.validated_data["employee_id"],
            serializer.validated_data["month"],
            serializer.validated_data["year"],
            serializer.validated_data["leave_dates"],
            serializer.validated_data.get("half_day_dates"),
            serializer.validated_data.get("permission_dates"),
        )
        return Response({"count": len(records), "employee_id": serializer.validated_data["employee_id"]}, status=status.HTTP_201_CREATED)

    @staticmethod
    @api_view(["GET"])
    @permission_classes([IsAuthenticated])
    def get_monthly_attendance(request):
        effective_user = resolve_target_user(request)
        emp_id = request.GET.get("employee_id")
        if not emp_id:
            raise BadRequestError("employee_id, month, and year are required query params")
        serializer = GenerateSlipsRequestSerializer(data=request.GET)
        serializer.is_valid(raise_exception=True)
        try:
            employee_id = int(emp_id)
        except ValueError as exc:
            raise BadRequestError("employee_id must be a valid number") from exc
        records = attendance_service.get_monthly_attendance(
            None, effective_user, employee_id,
            serializer.validated_data["month"], serializer.validated_data["year"],
        )
        return Response(AttendanceResponseSerializer(records, many=True).data)

    @staticmethod
    @api_view(["GET"])
    @permission_classes([IsAuthenticated])
    def get_readiness(request):
        effective_user = resolve_target_user(request)
        serializer = GenerateSlipsRequestSerializer(data=request.GET)
        serializer.is_valid(raise_exception=True)
        return Response(attendance_service.get_attendance_readiness(
            effective_user, serializer.validated_data["month"], serializer.validated_data["year"]
        ))

    @staticmethod
    @api_view(["GET"])
    @permission_classes([IsAuthenticated])
    def get_leave_summary(request):
        require_minimum_plan(request.user, PLAN_PROFESSIONAL, "Attendance summaries")
        effective_user = resolve_target_user(request)
        serializer = GenerateSlipsRequestSerializer(data=request.GET)
        serializer.is_valid(raise_exception=True)
        res = attendance_service.get_all_employees_leave_summary(
            None, effective_user, serializer.validated_data["month"], serializer.validated_data["year"],
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
        effective_user = resolve_target_user(request)
        try:
            from app.services.plan_notification_service import check_and_notify_plan_expiry
            check_and_notify_plan_expiry(request.user)
        except Exception:
            logging.getLogger(__name__).warning("Plan-expiry check failed for user %s", request.user.pk, exc_info=True)
        res = dashboard_service.get_dashboard_stats(None, effective_user)
        return Response(DashboardStatsSerializer(res).data)

    @staticmethod
    @api_view(["GET"])
    @permission_classes([IsAuthenticated])
    def get_payroll_summary(request):
        require_minimum_plan(request.user, PLAN_PROFESSIONAL, "Payroll dashboard and reports")
        effective_user = resolve_target_user(request)
        month = request.GET.get("month", datetime.now().month)
        year = request.GET.get("year", datetime.now().year)
        res = dashboard_service.get_payroll_summary(None, effective_user, int(month), int(year))
        return Response(PayrollSummarySerializer(res).data)

    @staticmethod
    @api_view(["GET"])
    @permission_classes([IsAuthenticated])
    def get_department_breakdown(request):
        require_minimum_plan(request.user, PLAN_ENTERPRISE, "Department-wise payroll insights")
        effective_user = resolve_target_user(request)
        res = dashboard_service.get_department_breakdown(None, effective_user)
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
    @api_view(["GET"])
    @permission_classes([IsAdmin])
    def list_companies(request):
        require_minimum_plan(request.user, PLAN_ENTERPRISE, "User and account administration")
        users = User.objects.all().select_related("company").order_by("full_name")
        data = []
        for u in users:
            company_obj = getattr(u, "company", None)
            c_name = company_obj.company_name if company_obj and company_obj.company_name else f"{u.full_name}'s Company"
            emp_count = u.employees.filter(is_active=True).count()
            data.append({
                "user_id": u.id,
                "user_name": u.full_name,
                "email": u.email,
                "role": u.role,
                "is_platform_admin": u.is_platform_admin,
                "is_active": u.is_active,
                "plan": u.plan,
                "company_name": c_name,
                "employee_count": emp_count,
            })
        return Response({"companies": data})

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


class AIAssistantViews:
    @staticmethod
    @api_view(["POST"])
    @permission_classes([IsAuthenticated])
    @throttle_classes([AIAssistantRateThrottle])
    def chat(request):
        require_minimum_plan(request.user, PLAN_PROFESSIONAL, "AI Assistant")
        serializer = AIAssistantChatRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reply = ask_assistant(
            request.user,
            serializer.validated_data["message"],
            history=serializer.validated_data.get("history", []),
        )
        return Response(AIAssistantChatResponseSerializer({"reply": reply}).data)


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def health_check(request):
    now_utc = datetime.now(timezone.utc)
    return Response({
        "status": "healthy",
        "app": settings.APP_NAME,
        "server_time_utc": now_utc.isoformat(),
        "timestamp_ms": int(now_utc.timestamp() * 1000),
    })


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def server_time(request):
    now_utc = datetime.now(timezone.utc)
    return Response({
        "server_time_utc": now_utc.isoformat(),
        "timestamp_ms": int(now_utc.timestamp() * 1000),
    })


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def root_view(request):
    return Response({
        "message": "Employee Salary Slip API is running.",
        "health_check": "/api/v1/health"
    })
