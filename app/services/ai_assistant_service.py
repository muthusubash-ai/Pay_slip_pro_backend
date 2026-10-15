import logging
from datetime import date

import httpx
from django.conf import settings

from app.models.user import User

logger = logging.getLogger(__name__)

OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"
GEMINI_CHAT_URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
MAX_EMPLOYEES_IN_CONTEXT = 50

def _get_system_prompt(user: User) -> str:
    company = getattr(user, "company", None)
    comp_name = (
        company.company_name
        if company and company.company_name
        else (user.company_name if getattr(user, "company_name", None) and user.company_name != "-" else "your company")
    )
    return (
        f"You are PaySlipPro AI, the intelligent, comprehensive, and friendly HR, Payroll, and Operations Business Partner "
        f"dedicated exclusively to {comp_name}. You possess complete domain expertise over this company, its employees, its attendance, and its payroll.\n\n"
        "Multi-Tenant Identity & Security Rules (MANDATORY):\n"
        f"1. Identity: You belong SOLELY to {comp_name}. When greeted or asked 'Who are you?', 'Who made you?', 'நீ யாரு?', or 'யார் நீங்கள்?', "
        f"introduce yourself warmly and proudly as {comp_name}'s PaySlipPro HR & Payroll AI Assistant.\n"
        "2. Strict Isolation: NEVER mention, assume, or reveal any other company name (do NOT mention Zigmaa Tech or third-party company names). "
        f"3. Data Boundary: You only know and are only permitted to discuss {comp_name}'s employees, salaries, and policies. "
        "You have zero access to any other company's database and must strictly refuse any request to view other organizations' data.\n\n"
        "Application Features & Architecture Knowledge:\n"
        "1. Dashboard: Provides high-level operational overview including Total & Active Employees, Total Monthly Payroll Budget, "
        "Current Month Salary Paid (from generated slips), Average Employee Salary, interactive attendance stats, and Department breakdown.\n"
        "2. Employees Management: Full employee lifecycle records including Employee Code (e.g. ZT0001, EMP001), designation, department, "
        "basic salary, allowances (HRA, Conveyance, Medical, Special), statutory deductions (PF 12%, ESI 0.75%, Professional Tax, TDS), "
        "Date of Joining, Bank Name, Bank Account Number, PAN Number, shift timings, and active status.\n"
        "3. Attendance & Biometrics:\n"
        "   - Monthly Attendance Grid (/attendance): Displays full monthly calendar with statuses: Present, Leave (unpaid), Half-day (0.5 deduction), "
        "Permission (free up to company allowance), Weekoff (shared pool allowance), and Company Week Off (structural recurring weekend off, e.g. Sunday).\n"
        "   - Biometric Kiosk (/biometric): Real-time face recognition / invite-code kiosk with GPS geofencing (must be within office radius, default 70m), "
        "camera verification photo, punch in/out timestamps, and automatic late arrival calculation against shift start time.\n"
        "   - Leave & Permission Requests: Employees submit leave/permission requests; admin/HR reviews, approves, or rejects them with remarks.\n"
        "   - Shared Monthly Weekoff Pool: Company provides 1 shared monthly Weekoff pool (worth 2 half-day units), which is distinct from structural company weekly offs like Sundays.\n"
        "4. Salary Slips & Payroll Processing:\n"
        "   - Slip Generation (/salary-slips/generate): Select month & year, choose employees, and generate slips.\n"
        "   - Formula: Per-Day Salary = Basic Salary / Total Days in Month.\n"
        "     Leave Deduction = (Full Unpaid Leaves * 1.0 + Half Days * 0.5 + Excess Permissions beyond company limit * 1.0) * Per-Day Salary.\n"
        "     Gross Salary = Basic Salary + Allowances. Statutory Deductions = PF + ESI + PT + TDS.\n"
        "     Net Pay = Gross Salary - Total Deductions.\n"
        "   - Slips can be viewed, downloaded as formatted PDF, or emailed directly to employee email addresses. Statuses: draft, generated, sent.\n"
        "5. Settings & Company Profile:\n"
        "   - Company Settings (/settings/company): Company name, logo upload, brand color theme, full address (street, city, state, zip), "
        "pay day (1st of month), financial year start, PF number, TAN number, office shift start & end times, employee shift override toggle, "
        "weekly off days (e.g. Sunday), free permission days allowance (e.g. 3 per month), and office GPS coordinates with geofence radius.\n"
        "   - Profile Settings (/settings): User full name, email, phone number, password management, and current subscription plan.\n"
        "   - Subscription Plans: Starter (Free, up to 3 employees), Professional (₹499/mo, up to 10 employees, branding, reports, AI assistant), "
        "Enterprise (₹999/mo, unlimited employees, department insights, user admin).\n"
        "6. Notification Settings:\n"
        "   - Email notifications configured via SMTP (Google Workspace / Gmail smtp.gmail.com:587 TLS).\n"
        "   - Automated branded payslip PDF delivery to employee emails upon clicking 'Email'.\n"
        "   - Biometric activation invitations sent via email with secure one-time invite digests.\n"
        "7. Language Preference:\n"
        "   - Fully bilingual in English ('en') and Tamil ('ta' - தமிழ்).\n"
        "   - Switchable at any time from the Language dropdown in the top navigation bar or settings menu. Saved in localStorage ('app_language').\n"
        "8. Theme Preference (Dark Theme / Light Theme):\n"
        "   - Supports high-contrast sleek Dark Mode and clean Light Mode.\n"
        "   - Toggleable instantly via the Sun/Moon icon in the top header navbar. Saved in localStorage ('theme'). Applies Tailwind dark: styling.\n\n"
        "Communication & Behavioral Rules:\n"
        "- Fluent Bilingual Communication: When the user asks in Tamil (தமிழ்) or Tanglish, reply fluently, politely, and warmly in Tamil/Tanglish. "
        "When asked in English, reply in professional English.\n"
        "- Complete Accuracy on Specific Dates: When asked about leaves, permissions, or attendance, refer to the exact dates provided in the live context "
        "(e.g. 'Kamala Priya 01-Oct, 07-Oct, 08-Oct, 09-Oct ஆகிய 4 தேதிகளில் leave எடுத்திருக்காங்க'). Never say dates are unknown if they are listed in context.\n"
        "- NEVER give robotic schema field recitals or say 'Based on the information provided, I know the following...'. Speak naturally as a capable partner.\n"
        "- Format currency amounts in Indian Rupees (₹) with commas (e.g. ₹30,000.00).\n"
        "- When calculating statistics or differences, perform accurate arithmetic."
    )


# Module-level default for backward-compatibility
SYSTEM_PROMPT = _get_system_prompt(None)


def _resolve_endpoint(api_key: str, configured_model: str) -> tuple[str, str, str]:
    """Resolves (provider, chat_url, model) based on settings and API key format."""
    ai_base_url = getattr(settings, "AI_BASE_URL", "").strip()
    if ai_base_url:
        chat_url = ai_base_url
        if not chat_url.endswith("/chat/completions") and not chat_url.endswith("/generate"):
            chat_url = chat_url.rstrip("/") + "/v1/chat/completions"
        model = configured_model or getattr(settings, "AI_MODEL", "gpt-4o")
        return "hermes", chat_url, model

    if api_key.startswith("sk-"):
        return "openai", OPENAI_CHAT_URL, configured_model if configured_model and "gemini" not in configured_model.lower() else "gpt-4o-mini"

    gemini_key = getattr(settings, "GEMINI_API_KEY", "")
    is_gemini = (
        api_key.startswith("AQ.")
        or api_key.startswith("AIza")
        or "gemini" in (configured_model or "").lower()
        or bool(gemini_key and api_key == gemini_key)
    )
    if is_gemini:
        model = configured_model if "gemini" in (configured_model or "").lower() else "gemini-2.5-flash"
        return "gemini", GEMINI_CHAT_URL, model
    return "openai", OPENAI_CHAT_URL, configured_model or "gpt-4o-mini"


def _build_context(user: User) -> str:
    from collections import defaultdict
    from datetime import timedelta
    from app.models.employee import Employee
    from app.models.salary_slip import SalarySlip
    from app.models.attendance import Attendance as DailyAttendance, AttendanceStatus
    from app.services.attendance_service import get_all_employees_leave_summary

    today = date.today()
    month, year = today.month, today.year
    prev_date = today.replace(day=1) - timedelta(days=1)
    prev_month, prev_year = prev_date.month, prev_date.year

    lines = [f"Today's date: {today.isoformat()}"]

    # 1. User Profile & Account Details
    user_plan = getattr(user, "plan", "starter").capitalize()
    user_role = getattr(user, "role", "hr_manager")
    lines.append(f"\nAccount & Profile Info:")
    lines.append(f"- User: {user.full_name} ({user.email})")
    lines.append(f"- Phone: {user.phone or 'Not configured'}")
    lines.append(f"- Subscription Plan: {user_plan} Plan (Role: {user_role})")

    # 2. Company Settings, Policies & Biometric Geofencing
    company = getattr(user, "company", None)
    if company:
        lines.append(f"\nCompany Settings & Policies:")
        lines.append(f"- Company Name: {company.company_name}")
        lines.append(f"- Pay Day: {company.pay_day} of each month")
        lines.append(f"- Free Permission Days: {company.permission_days_per_month} per month (0 deduction up to {company.permission_days_per_month} requests)")
        lines.append(f"- Office Shift Timings: {company.office_start_time} to {company.office_end_time} ({company.office_timing or 'Standard'})")
        lines.append(f"- Shift Override per Employee Enabled: {company.enable_employee_shift_timing}")
        lines.append(f"- Company Weekly Off Days: {company.weekly_off_days or [6]} (e.g. Sunday)")
        if company.address:
            addr_full = ", ".join(p for p in (company.address, company.city, company.state, company.zip_code) if p)
            lines.append(f"- Company Address: {addr_full}")
        if company.pf_number:
            lines.append(f"- Company PF Number: {company.pf_number}")
        if company.tan_number:
            lines.append(f"- Company TAN Number: {company.tan_number}")
        if company.office_lat and company.office_lng:
            lines.append(
                f"- Biometric Geofencing: Lat {company.office_lat}, Lng {company.office_lng} "
                f"(Allowed punch radius: {company.allowed_radius_meters}m)"
            )
    else:
        lines.append("\nCompany profile has not been configured yet.")

    # 3. Dashboard High-Level Metrics & Department Breakdown
    has_pk = bool(getattr(user, "pk", None))
    employees_qs = Employee.objects.filter(user=user, is_active=True).order_by("full_name") if has_pk else Employee.objects.none()
    total_employees = employees_qs.count()
    employees = list(employees_qs[:MAX_EMPLOYEES_IN_CONTEXT])
    total_payroll_budget = sum((float(emp.basic_salary) for emp in employees_qs), 0.0)

    # Current month salary slips paid/generated
    slips_curr_month = SalarySlip.objects.filter(user=user, month=month, year=year) if has_pk else SalarySlip.objects.none()
    curr_month_paid = sum((float(s.net_pay) for s in slips_curr_month), 0.0)
    avg_salary = (total_payroll_budget / total_employees) if total_employees > 0 else 0.0

    dept_counts = defaultdict(int)
    for emp in employees_qs:
        dept_counts[emp.department or "General"] += 1
    dept_str = ", ".join(f"{d}: {c} employees" for d, c in dept_counts.items())

    lines.append(f"\nDashboard Live Summary:")
    lines.append(f"- Total Active Employees: {total_employees}")
    lines.append(f"- Total Monthly Basic Salary Budget: ₹{total_payroll_budget:,.2f}")
    lines.append(f"- Current Month ({month}/{year}) Slips Generated: {slips_curr_month.count()} slips (Total Net Pay: ₹{curr_month_paid:,.2f})")
    lines.append(f"- Average Employee Basic Salary: ₹{avg_salary:,.2f}")
    lines.append(f"- Department Breakdown: {dept_str}")

    # 4. Employee Master Records (Salaries, Bank, PAN, Joining, Timings)
    lines.append("\nEmployee Master Records:")
    for emp in employees:
        desig = emp.designation or "Employee"
        dept = emp.department or "General"
        phone = emp.phone or "N/A"
        email = emp.email or "N/A"
        doj = emp.date_of_joining.strftime("%d-%b-%Y") if emp.date_of_joining else "N/A"
        acct_mask = f" (A/C ending in {emp.bank_account_number[-4:]})" if emp.bank_account_number and len(emp.bank_account_number) >= 4 else (f" (A/C: {emp.bank_account_number})" if emp.bank_account_number else "")
        bank_info = f"{emp.bank_name or 'N/A'}{acct_mask}"
        pan_info = emp.pan_number or "N/A"
        shift_info = f", Shift: {emp.shift_start_time} - {emp.shift_end_time}" if emp.shift_start_time and emp.shift_end_time else ""
        lines.append(
            f"- {emp.full_name} ({emp.employee_code}): {desig} in {dept}, Basic Salary: ₹{emp.basic_salary}, "
            f"Date of Joining: {doj}, Bank: {bank_info}, PAN: {pan_info}, Phone: {phone}, Email: {email}{shift_info}"
        )

    # 5. Detailed Daily Attendance for Current Month (WITH EXACT DATES FOR LEAVES, HALF-DAYS, PERMISSIONS)
    curr_records = DailyAttendance.objects.filter(
        user=user,
        date__year=year,
        date__month=month
    ).exclude(status__in=[AttendanceStatus.present, AttendanceStatus.company_week_off]).order_by("date")

    curr_leaves_by_emp = defaultdict(lambda: defaultdict(list))
    for r in curr_records:
        curr_leaves_by_emp[r.employee_id][r.status].append(r.date.strftime("%d-%b"))

    try:
        summary = get_all_employees_leave_summary(None, user, month, year)
    except Exception:
        logger.warning("AI assistant: failed to build leave summary context", exc_info=True)
        summary = []
    summary_by_emp = {s["employee_id"]: s for s in summary}

    lines.append(f"\nCurrent Month ({month}/{year}) Detailed Attendance & Payroll per Employee:")
    for emp in employees:
        s = summary_by_emp.get(emp.id)
        if s:
            emp_dates = curr_leaves_by_emp.get(emp.id, {})
            detail_parts = []
            if "leave" in emp_dates:
                detail_parts.append(f"Leaves ({len(emp_dates['leave'])} days): {', '.join(emp_dates['leave'])}")
            if "half_day" in emp_dates:
                detail_parts.append(f"Half-Days ({len(emp_dates['half_day'])} days): {', '.join(emp_dates['half_day'])}")
            if "permission" in emp_dates:
                detail_parts.append(f"Permissions ({len(emp_dates['permission'])} days): {', '.join(emp_dates['permission'])}")
            if "weekoff" in emp_dates:
                detail_parts.append(f"Weekoff Pool ({len(emp_dates['weekoff'])} days): {', '.join(emp_dates['weekoff'])}")
            if "weekoff_halfday" in emp_dates:
                detail_parts.append(f"Weekoff Half-Days ({len(emp_dates['weekoff_halfday'])} days): {', '.join(emp_dates['weekoff_halfday'])}")

            dates_str = f" [Exact Dates -> {'; '.join(detail_parts)}]" if detail_parts else " [No leaves or permissions taken this month - Perfect Attendance!]"
            lines.append(
                f"- {emp.full_name} ({emp.employee_code}): Present {s['present_days']}/{s['total_days']} days, "
                f"Leaves: {s['leave_days']}, Half-Days: {s.get('half_day_days', 0)}, Permissions: {s.get('permission_days', 0)}, "
                f"Weekoffs: {s['weekoff_days']}, Company Week Offs: {s.get('company_week_off_days', 0)}, "
                f"Leave Deduction: ₹{s['leave_deduction']}, Net Payable This Month: ₹{s['net_payable']}.{dates_str}"
            )
        else:
            lines.append(f"- {emp.full_name} ({emp.employee_code}): No attendance recorded yet for this month.")

    # 6. Previous Month ({prev_month}/{prev_year}) Non-Present Attendance Records (Leaves with Exact Dates)
    prev_records = DailyAttendance.objects.filter(
        user=user,
        date__year=prev_year,
        date__month=prev_month
    ).exclude(status__in=[AttendanceStatus.present, AttendanceStatus.company_week_off]).order_by("date")

    if prev_records.exists():
        prev_leaves_by_emp = defaultdict(lambda: defaultdict(list))
        for r in prev_records:
            prev_leaves_by_emp[r.employee_id][r.status].append(r.date.strftime("%d-%b"))
        lines.append(f"\nPrevious Month ({prev_month}/{prev_year}) Leave Records with Exact Dates:")
        for emp_id, st_map in prev_leaves_by_emp.items():
            emp_obj = next((e for e in employees if e.id == emp_id), None)
            if emp_obj:
                emp_str_parts = []
                for st, dates in st_map.items():
                    emp_str_parts.append(f"{st} ({len(dates)} days: {', '.join(dates)})")
                lines.append(f"- {emp_obj.full_name} ({emp_obj.employee_code}): {'; '.join(emp_str_parts)}")

    # 7. Today's Live Biometric Punches & Leave Requests
    try:
        from attendance.models import Attendance as KioskAttendance, LeaveRequest
        today_attendances = KioskAttendance.objects.filter(
            employee__payroll_employee__user=user,
            date=today
        ).select_related("employee__payroll_employee")

        checked_in_count = today_attendances.count()
        lines.append(f"\nToday's Live Biometric Attendance ({today.isoformat()}): {checked_in_count} of {total_employees} employees present")
        if today_attendances.exists():
            for att in today_attendances:
                lines.append(
                    f"- {att.employee.full_name} ({att.employee.emp_id}): Checked in at {att.check_in or 'N/A'}, "
                    f"Status: {att.status}, Checked out at: {att.check_out or 'Currently working'}"
                )
        else:
            lines.append("No employees have punched in at the biometric kiosk yet today.")

        pending_leaves = LeaveRequest.objects.filter(
            employee__payroll_employee__user=user,
            status="PENDING"
        ).select_related("employee__payroll_employee")[:10]
        if pending_leaves.exists():
            lines.append("\nPending Leave & Permission Requests awaiting approval:")
            for req in pending_leaves:
                lines.append(
                    f"- {req.employee.full_name} ({req.employee.emp_id}): {req.request_type} "
                    f"from {req.start_date} to {req.end_date} (Status: PENDING)"
                )
    except Exception as e:
        logger.debug("AI assistant context: live attendance details omitted (%s)", e)

    # 8. Salary Slip History with Timestamps
    recent_slips = (
        SalarySlip.objects.filter(user=user)
        .select_related("employee")
        .order_by("-year", "-month", "-generated_at")[:MAX_EMPLOYEES_IN_CONTEXT]
    )
    if recent_slips:
        lines.append("\nRecently Generated Salary Slips:")
        for slip in recent_slips:
            gen_date = slip.generated_at.strftime("%d-%b-%Y %I:%M %p") if slip.generated_at else "Date not recorded"
            email_info = f", Emailed on: {slip.emailed_at.strftime('%d-%b-%Y %I:%M %p')}" if slip.emailed_at else ", Not yet emailed"
            lines.append(
                f"- {slip.employee.full_name} ({slip.employee.employee_code}): {slip.month}/{slip.year} Payslip — "
                f"Generated on: {gen_date}{email_info}, Status: {slip.status}, "
                f"Gross: ₹{slip.gross_salary}, Basic: ₹{slip.basic_salary}, "
                f"Leave Deduction: ₹{slip.leave_deduction} ({slip.leave_days} leave days), "
                f"Total Deductions: ₹{slip.total_deductions}, Net Pay: ₹{slip.net_pay}."
            )

    return "\n".join(lines)


def _fallback_answer(user: User, message: str) -> str:
    """Intelligent database-grounded local answer when upstream OpenAI API is unreachable or quota exhausted."""
    from app.models.employee import Employee
    from app.models.salary_slip import SalarySlip
    from app.services.attendance_service import get_all_employees_leave_summary

    msg = message.strip().lower()
    company = getattr(user, "company", None)
    comp_name = (
        company.company_name
        if company and company.company_name
        else (user.company_name if getattr(user, "company_name", None) and user.company_name != "-" else "Your Company")
    )
    today = date.today()
    month, year = today.month, today.year
    has_pk = bool(getattr(user, "pk", None))
    active_employees_qs = Employee.objects.filter(user=user, is_active=True) if has_pk else Employee.objects.none()

    # Check for assistant identity ("who are you", "nee yaaru", etc.)
    if any(k in msg for k in ["who are you", "who r u", "who made you", "nee yaaru", "ne yaaru", "yaar neenga", "யாரு", "யார்"]):
        qs_count = active_employees_qs.count()
        return (
            f"👋 நான் **{comp_name}**-ன் அதிகாரப்பூர்வ **PaySlipPro AI Assistant**!\n\n"
            f"நான் **{comp_name}** நிறுவனத்தின் ஊழியர்கள் விவரங்கள் ({qs_count} active employees), வருகைப் பதிவு (Attendance & Biometric), "
            f"சம்பளக் கணக்கீடு (Salary Slips & Deductions), மற்றும் நிறுவன கொள்கைகள் (Company Policies) குறித்த உதவிகளை வழங்கத் தயார்.\n\n"
            f"🔒 **Multi-Tenant Security:** நான் {comp_name} நிறுவனத்தின் தரவுகளை மட்டுமே பாதுகாப்பாக அணுக முடியும்; பிற நிறுவனங்களின் தரவுகளுக்கு இங்கு அனுமதி இல்லை.\n\n"
            f"உங்களுக்கு {comp_name} குறித்து என்ன உதவி தேவைப்படுகிறது?"
        )

    # Check for employee count or employee list
    if any(k in msg for k in ["how many employee", "total employee", "list employee", "employees"]):
        qs = active_employees_qs.order_by("full_name")
        total = qs.count()
        if total == 0:
            return f"You currently have no active employees registered under {comp_name}. You can add new employees from the Employees section."
        names = [f"• {e.full_name} ({e.employee_code}) - ₹{e.basic_salary:,.2f}" for e in qs[:10]]
        more = f"\n...and {total - 10} more." if total > 10 else ""
        return f"📊 **{comp_name}** currently has **{total} active employees**:\n" + "\n".join(names) + more

    # Check for specific employee by full name, code, or first/last name part
    qs = active_employees_qs
    matched_emp = None
    msg_words = [w.strip("?,.!") for w in msg.split()]
    for emp in qs:
        emp_name_lower = emp.full_name.lower()
        if emp_name_lower in msg or (emp.employee_code and emp.employee_code.lower() in msg):
            matched_emp = emp
            break
        name_parts = [p.strip().lower() for p in emp.full_name.split() if len(p.strip()) >= 3]
        if any(part in msg_words or f" {part} " in f" {msg} " for part in name_parts):
            matched_emp = emp
            break

    if matched_emp:
        try:
            summary = get_all_employees_leave_summary(None, user, month, year)
            emp_summary = next((s for s in summary if s["employee_id"] == matched_emp.id), None)
        except Exception:
            emp_summary = None

        res = [
            f"👤 **Employee Details: {matched_emp.full_name}**",
            f"• **Code:** {matched_emp.employee_code}",
            f"• **Designation:** {matched_emp.designation or 'Not specified'}",
            f"• **Department:** {matched_emp.department or 'General'}",
            f"• **Basic Salary:** ₹{matched_emp.basic_salary:,.2f}",
        ]
        if emp_summary:
            res.extend([
                f"• **Current Month ({month}/{year}) Attendance:** {emp_summary['present_days']}/{emp_summary['total_days']} days present",
                f"• **Leaves Taken:** {emp_summary['leave_days']} days",
                f"• **Leave Deduction:** ₹{emp_summary['leave_deduction']:,.2f}",
                f"• **Estimated Net Payable:** ₹{emp_summary['net_payable']:,.2f}",
            ])
            # Fetch exact leave, permission, and half-day dates
            try:
                from collections import defaultdict
                from app.models.attendance import Attendance as DailyAttendance, AttendanceStatus
                leave_rows = DailyAttendance.objects.filter(
                    user=user,
                    employee=matched_emp,
                    date__year=year,
                    date__month=month
                ).exclude(status__in=[AttendanceStatus.present, AttendanceStatus.company_week_off]).order_by("date")
                st_dates = defaultdict(list)
                for lr in leave_rows:
                    st_dates[lr.status].append(lr.date.strftime("%d-%b"))
                if "leave" in st_dates:
                    res.append(f"• **Exact Leave Dates ({len(st_dates['leave'])} days):** {', '.join(st_dates['leave'])}")
                if "half_day" in st_dates:
                    res.append(f"• **Exact Half-Day Dates ({len(st_dates['half_day'])} days):** {', '.join(st_dates['half_day'])}")
                if "permission" in st_dates:
                    res.append(f"• **Exact Permission Dates ({len(st_dates['permission'])} days):** {', '.join(st_dates['permission'])}")
            except Exception:
                pass
        return "\n".join(res)

    # Net pay / Salary Calculation
    if any(k in msg for k in ["net pay", "salary calculate", "how is salary", "deduction", "gross", "formula"]):
        return (
            f"💰 **How Salary & Net Pay is Calculated for {comp_name}:**\n\n"
            "1. **Per Day Salary** = Basic Salary ÷ Total Days in Month.\n"
            "2. **Gross Salary** = Basic Salary + Allowances (HRA, DA, Conveyance, Special Allowance).\n"
            "3. **Leave Deduction** = (Unpaid Leaves × 1.0 + Half-Days × 0.5 + Excess Permissions beyond free limit × 1.0) × Per Day Salary.\n"
            "4. **Statutory Deductions** = Provident Fund (PF) + ESI + Professional Tax + TDS (if applicable).\n"
            "5. **Net Pay** = Gross Salary − Leave Deductions − Statutory Deductions.\n\n"
            f"For {comp_name}, employees receive free permission days ({getattr(company, 'permission_days_per_month', 3)} per month) without salary deductions."
        )

    # Theme / Dark mode / Light mode
    if any(k in msg for k in ["theme", "dark mode", "light mode", "dark theme", "light theme"]):
        return (
            "🌓 **Dark & Light Theme Support:**\n\n"
            "• **How to Switch:** Click the **Sun / Moon icon** in the top navigation bar at any time to toggle between Dark Mode and Light Mode.\n"
            "• **Storage:** Your preference is automatically remembered and saved in your browser's local storage (`theme`).\n"
            "• **Design:** Sleek glassmorphic styling adapts seamlessly with vibrant gradients in both themes!"
        )

    # Language Preference / Tamil / English
    if any(k in msg for k in ["language", "tamil", "english", "மொழி"]):
        return (
            "🌐 **Language Preferences (தமிழ் / English):**\n\n"
            "• **How to Switch:** Click the **Language dropdown (EN / TA)** in the top navigation bar or settings menu.\n"
            "• **Support:** PaySlipPro provides full native bilingual support in **English** and **Tamil (தமிழ்)** across all pages.\n"
            "• **Storage:** Your preferred language is saved in `localStorage.app_language` and applies automatically."
        )

    # Notification & Email Settings
    if any(k in msg for k in ["notification", "email setting", "smtp", "mail"]):
        return (
            "🔔 **Notification & Email Delivery Settings:**\n\n"
            "• **SMTP Delivery:** Automated emails are routed via secure TLS SMTP (`smtp.gmail.com:587`).\n"
            "• **Salary Slip Delivery:** Once payslips are generated, clicking **'Email'** sends the official PDF slip directly to the employee's registered email address.\n"
            "• **Biometric Invites:** Employee activation invites are sent with one-time verification links to register for the biometric face kiosk."
        )

    # Profile & Subscription Plan
    if any(k in msg for k in ["profile", "plan", "subscription", "upgrade"]):
        plan_name = getattr(user, "plan", "starter").capitalize()
        return (
            f"👤 **Profile & Subscription Details:**\n\n"
            f"• **Account Owner:** {user.full_name} ({user.email})\n"
            f"• **Phone:** {user.phone or 'Not configured'}\n"
            f"• **Current Plan:** **{plan_name} Plan**\n"
            f"• **Role:** {getattr(user, 'role', 'hr_manager')}\n"
            "• **Plans Available:** Starter (Free, up to 3 employees), Professional (₹499/mo, up to 10 employees, logo & reports), Enterprise (₹999/mo, unlimited employees & insights).\n"
            "• **Upgrade:** You can upgrade anytime in **Settings → Subscription Plan** via Razorpay."
        )

    # Leave rules & Attendance Punch
    if any(k in msg for k in ["leave", "permission", "attendance", "punch", "biometric", "face scan"]):
        return (
            "📅 **Attendance & Leave Rules:**\n\n"
            f"• **Pay Day:** {getattr(company, 'pay_day', 1)} of every month.\n"
            f"• **Free Permissions:** {getattr(company, 'permission_days_per_month', 3)} per month (no salary deduction).\n"
            "• **Biometric / Face Scan:** Employees can punch in/out using the `/biometric` kiosk portal with camera face recognition or employee invite code within the 70m geofence radius.\n"
            "• **Attendance Statuses:** Present, Half Day, Leave, Permission, Week Off, and Company Week Off.\n"
            "• **Late Mark / Unapproved Absence:** Automatically computes daily salary deduction based on monthly days."
        )

    # Salary Slips generation
    if any(k in msg for k in ["salary slip", "payslip", "generate slip", "download pdf", "email slip"]):
        slips_count = SalarySlip.objects.filter(user=user).count() if has_pk else 0
        return (
            f"📄 **Salary Slip Generation & Distribution:**\n\n"
            f"• Total slips generated so far: **{slips_count}**.\n"
            "• **To generate new slips:** Navigate to **Salary Slips → Generate Slips**, select the month & year, choose employees, and click **Generate**.\n"
            "• **PDF & Email:** Once generated, click **Download PDF** for a printable payslip or click **Email** to send it directly to the employee's registered email address.\n"
            "• Slips lock attendance and leave records for the payroll cycle."
        )

    # Company settings
    if any(k in msg for k in ["company", "policy", "pay day", "setting"]):
        if company:
            address_parts = [p for p in (company.address, company.city, company.state) if p]
            return (
                f"🏢 **Company Information:**\n\n"
                f"• **Name:** {company.company_name}\n"
                f"• **Pay Day:** {company.pay_day} of each month\n"
                f"• **Free Permissions:** {company.permission_days_per_month} per month\n"
                f"• **Account Email:** {user.email}\n"
                f"• **Address:** {', '.join(address_parts) if address_parts else 'Not set'}"
            )
        return "Company settings have not been configured yet. You can set them up in Company Settings."

    # General fallback
    qs = active_employees_qs
    return (
        f"👋 Hello! I'm your **PaySlipPro AI Assistant** for {comp_name}.\n\n"
        f"You currently have **{qs.count()} active employees**. I can help you with:\n"
        "• Employee payroll, basic salary & net payable summaries\n"
        "• Current month attendance, leaves, and biometric punches\n"
        "• Salary slip calculations, deductions, and PDF downloads\n"
        "• Company policies, pay days, and permission allowances\n\n"
        "Feel free to ask a specific question like *'How is John's salary calculated?'* or *'How many employees are active?'*!"
    )


def ask_assistant(user: User, message: str, history: list[dict] | None = None) -> str:
    """Ask the configured Gemini / OpenAI model a question, grounded in this owner's own company data
    and the prior turns of this conversation (history), so the assistant has memory of what was already
    asked/answered. Falls back gracefully to intelligent database-grounded local response if upstream LLM
    is unreachable."""
    ai_base_url = (getattr(settings, "AI_BASE_URL", "") or "").strip()
    ai_api_key = (getattr(settings, "AI_API_KEY", "") or "").strip()
    ai_model = (getattr(settings, "AI_MODEL", "") or "").strip()
    gemini_key = (getattr(settings, "GEMINI_API_KEY", "") or "").strip()
    openai_key = (getattr(settings, "OPENAI_API_KEY", "") or "").strip()

    if ai_base_url:
        api_key = ai_api_key or "hermes-local"
        configured_model = ai_model or "gpt-4o"
    elif openai_key and openai_key.startswith("sk-"):
        api_key = openai_key
        configured_model = getattr(settings, "OPENAI_MODEL", "gpt-4o-mini")
    elif gemini_key:
        api_key = gemini_key
        configured_model = getattr(settings, "GEMINI_MODEL", "gemini-2.5-flash")
    elif openai_key:
        api_key = openai_key
        configured_model = getattr(settings, "OPENAI_MODEL", "gemini-2.5-flash")
    else:
        api_key = ""
        configured_model = ""

    if not api_key:
        return _fallback_answer(user, message)

    provider, chat_url, model = _resolve_endpoint(api_key, configured_model)

    context = _build_context(user)
    system_prompt = _get_system_prompt(user)
    history_messages = [
        {"role": h["role"], "content": h["content"]} for h in (history or [])
    ]
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "system", "content": f"CONTEXT DATA:\n{context}"},
            *history_messages,
            {"role": "user", "content": message},
        ],
        "temperature": 0.3,
        "max_tokens": 800,
    }

    try:
        response = httpx.post(
            chat_url,
            json=payload,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=30.0,
        )
        response.raise_for_status()
        data = response.json()
        choices = data.get("choices") or []
        if choices and choices[0].get("message", {}).get("content"):
            return choices[0]["message"]["content"].strip()
    except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.HTTPError) as exc:
        logger.warning("AI assistant upstream call to %s failed (%s), trying native fallback if applicable", provider, exc)
        if provider == "gemini":
            try:
                native_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
                # Gemini's native API uses role "model" for the assistant turn, not "assistant".
                gemini_history = [
                    {"role": "model" if h["role"] == "assistant" else "user", "parts": [{"text": h["content"]}]}
                    for h in (history or [])
                ]
                native_payload = {
                    "system_instruction": {"parts": [{"text": f"{system_prompt}\n\nCONTEXT DATA:\n{context}"}]},
                    "contents": [*gemini_history, {"role": "user", "parts": [{"text": message}]}],
                    "generationConfig": {"temperature": 0.3, "maxOutputTokens": 800}
                }
                res = httpx.post(native_url, json=native_payload, timeout=30.0)
                if res.status_code == 200:
                    cand = res.json().get("candidates") or []
                    if cand and cand[0].get("content", {}).get("parts"):
                        return cand[0]["content"]["parts"][0]["text"].strip()
            except Exception as e:
                logger.warning("Native Gemini fallback failed (%s)", e)
        return _fallback_answer(user, message)
    except Exception as exc:
        logger.warning("AI assistant unexpected error (%s), using local DB fallback", exc)
        return _fallback_answer(user, message)

    return _fallback_answer(user, message)

