import calendar
import logging
from datetime import date
from django.db import transaction
from django.db.models import F

from app.exceptions import BadRequestError, NotFoundError
from app.models.attendance import Attendance, AttendanceStatus
from app.models.employee import Employee
from app.models.user import User

logger = logging.getLogger(__name__)


# The company-provided monthly Weekoff is a single shared pool worth 2 half-day units.
# A full-day leave costs 2 units (all-or-nothing - no partial credit); a half-day leave
# costs 1 unit. Whichever leaves come first chronologically draw from the pool first.
WEEKOFF_POOL_UNITS_PER_MONTH = 2


def allocate_weekoff_pool(
    full_day_dates: set[date], half_day_dates: set[date]
) -> tuple[dict[date, str], dict[date, str]]:
    """Allocate the shared monthly Weekoff pool across full-day and half-day leave dates,
    in chronological order. Returns (leave_status_by_date, half_day_status_by_date)."""
    combined = sorted(
        [(d, "full") for d in full_day_dates] + [(d, "half") for d in half_day_dates]
    )
    remaining = WEEKOFF_POOL_UNITS_PER_MONTH
    leave_status_by_date: dict[date, str] = {}
    half_day_status_by_date: dict[date, str] = {}
    for d, kind in combined:
        if kind == "full":
            if remaining >= 2:
                leave_status_by_date[d] = AttendanceStatus.weekoff
                remaining -= 2
            else:
                leave_status_by_date[d] = AttendanceStatus.leave
        else:
            if remaining >= 1:
                half_day_status_by_date[d] = AttendanceStatus.weekoff_halfday
                remaining -= 1
            else:
                half_day_status_by_date[d] = AttendanceStatus.half_day
    return leave_status_by_date, half_day_status_by_date


def get_weekly_off_weekdays(user: User) -> set[int]:
    """Company's configured recurring weekly off days (Monday=0 ... Sunday=6)."""
    company = getattr(user, "company", None)
    return set(company.weekly_off_days or []) if company else set()


def get_permission_allowance(user: User) -> int:
    """Company's configured free permission requests per month (0 deduction up to this count)."""
    company = getattr(user, "company", None)
    if not company or company.permission_days_per_month is None:
        return 3
    return company.permission_days_per_month


def mark_attendance(
    db, user: User, employee_id: int, att_date: date, status: str
) -> Attendance:
    """Mark attendance for a single employee on a single date."""
    try:
        employee = Employee.objects.get(id=employee_id, user=user)
    except Employee.DoesNotExist:
        raise NotFoundError("Employee")

    if att_date < employee.date_of_joining:
        raise BadRequestError(
            f"Attendance cannot be marked before {employee.full_name}'s joining date ({employee.date_of_joining})."
        )

    att_status = status

    try:
        existing = Attendance.objects.get(employee_id=employee_id, date=att_date)
        existing.status = att_status
        existing.save()
        return existing
    except Attendance.DoesNotExist:
        record = Attendance(
            user=user,
            employee=employee,
            date=att_date,
            status=att_status,
        )
        record.save()
        return record


def bulk_mark_leaves(
    db,
    user: User,
    employee_id: int,
    month: int,
    year: int,
    leave_dates: list[date],
    half_day_dates: list[date] | None = None,
    permission_dates: list[date] | None = None,
) -> list[Attendance]:
    """Mark leave, half-day and permission dates for an employee in a given month.

    The company-provided monthly Weekoff is a single shared pool worth 2 half-day
    units (see allocate_weekoff_pool). A full-day leave costs 2 units; a half-day
    leave costs 1 unit; whichever comes first chronologically draws from the pool
    first, and there's no partial credit (e.g. if only 1 unit remains, a full-day
    leave still deducts the full 1.0 day rather than 0.5).

    Dates that fall on the company's configured recurring weekly off day(s)
    (e.g. every Sunday) always win as `company_week_off` regardless of what was
    passed in for that date, and never consume the monthly Weekoff pool above.
    """
    try:
        employee = Employee.objects.get(id=employee_id, user=user)
    except Employee.DoesNotExist:
        raise NotFoundError("Employee")

    weekly_off_weekdays = get_weekly_off_weekdays(user)
    permission_allowance = get_permission_allowance(user)
    total_days = calendar.monthrange(year, month)[1]
    start_date = date(year, month, 1)
    end_date = date(year, month, total_days)
    if end_date < employee.date_of_joining:
        raise BadRequestError(
            f"Attendance cannot be saved before {employee.full_name}'s joining date ({employee.date_of_joining})."
        )
    first_active_date = max(start_date, employee.date_of_joining)
    selected_dates = (
        set(leave_dates)
        | set(half_day_dates or [])
        | set(permission_dates or [])
    )
    if any(day < first_active_date or day > end_date for day in selected_dates):
        raise BadRequestError("Attendance dates must be on or after the employee's joining date in the selected month.")

    with transaction.atomic():
        # Delete existing records for this employee/month
        Attendance.objects.filter(
            employee_id=employee_id,
            date__range=(start_date, end_date)
        ).delete()

        # Weekly off dates always win and never consume the monthly Weekoff pool,
        # so they're excluded here before allocating the shared pool.
        permission_set = {d for d in (permission_dates or []) if d.weekday() not in weekly_off_weekdays}
        full_day_dates = {d for d in set(leave_dates) if d.weekday() not in weekly_off_weekdays}
        half_day_dates_filtered = {d for d in set(half_day_dates or []) if d.weekday() not in weekly_off_weekdays}
        leave_status_by_date, half_day_status_by_date = allocate_weekoff_pool(
            full_day_dates, half_day_dates_filtered
        )

        records = []
        for day in range(first_active_date.day, total_days + 1):
            d = date(year, month, day)
            if d.weekday() in weekly_off_weekdays:
                status = AttendanceStatus.company_week_off
            elif d in leave_status_by_date:
                status = leave_status_by_date[d]
            elif d in half_day_status_by_date:
                status = half_day_status_by_date[d]
            elif d in permission_set:
                status = AttendanceStatus.permission
            else:
                status = AttendanceStatus.present

            record = Attendance(
                user=user,
                employee=employee,
                date=d,
                status=status,
            )
            record.save()
            records.append(record)

        # Calculate effective leave days:
        # Full day leave = 1.0 day (dates allocated as Weekoff from the shared pool are excluded)
        # Half day leave = 0.5 day (dates allocated as Weekoff Halfday from the pool are excluded)
        # Permission: up to the company's configured allowance per month is free (0 deduction).
        # Any permissions beyond that are considered as 1 day leave each (1.0 deduction each).
        excess_permissions = max(0, len(permission_set) - permission_allowance)
        effective_full_leaves = sum(1 for s in leave_status_by_date.values() if s == AttendanceStatus.leave)
        effective_half_days = sum(1 for s in half_day_status_by_date.values() if s == AttendanceStatus.half_day)
        effective_leave_days = (
            effective_full_leaves * 1.0 +
            effective_half_days * 0.5 +
            excess_permissions * 1.0
        )

        # Automatically synchronize existing SalarySlip if one was already generated
        try:
            from app.models.salary_slip import SalarySlip
            existing_slip = SalarySlip.objects.filter(
                user=user,
                employee_id=employee_id,
                month=month,
                year=year,
            ).first()
            if existing_slip:
                leave_ded = calculate_leave_deduction(float(employee.basic_salary), effective_leave_days, month, year)
                existing_slip.leave_days = int(round(effective_leave_days))
                existing_slip.leave_deduction = leave_ded
                gross = float(existing_slip.gross_salary)
                deductions = float(existing_slip.total_deductions)
                existing_slip.net_pay = round(gross - deductions - leave_ded, 2)
                existing_slip.save()
        except Exception as e:
            logger.warning("Could not auto-sync salary slip with updated attendance: %s", e)

    return records


def get_monthly_attendance(
    db, user: User, employee_id: int, month: int, year: int
) -> list[dict]:
    """Get all attendance records for an employee in a month, enriched with Biometric punches & working hours."""
    try:
        employee = Employee.objects.get(id=employee_id, user=user)
    except Employee.DoesNotExist:
        raise NotFoundError("Employee")
    total_days = calendar.monthrange(year, month)[1]
    start_date = date(year, month, 1)
    end_date = date(year, month, total_days)
    if end_date < employee.date_of_joining:
        return []

    first_active_date = max(start_date, employee.date_of_joining)
    weekly_off_weekdays = get_weekly_off_weekdays(user)

    # 1. Fetch saved Pay Slip Pro attendance records
    saved_records = {
        att.date: att for att in Attendance.objects.filter(
            employee_id=employee_id,
            user=user,
            date__range=(first_active_date, end_date)
        )
    }

    # 2. Fetch biometric records and leave requests from the biometric portal
    biometric_records = {}
    approved_leaves = {}
    try:
        from attendance.models import Employee as BioEmployee, Attendance as BioAttendance, LeaveRequest
        bio_emp = BioEmployee.objects.filter(payroll_employee=employee).first()

        if bio_emp:
            for b_att in BioAttendance.objects.filter(employee=bio_emp, date__gte=start_date, date__lte=end_date):
                biometric_records[b_att.date] = b_att

            for l_req in LeaveRequest.objects.filter(employee=bio_emp, status='APPROVED', start_date__lte=end_date, end_date__gte=start_date):
                curr = max(start_date, l_req.start_date)
                req_end = min(end_date, l_req.end_date)
                from datetime import timedelta
                while curr <= req_end:
                    approved_leaves[curr] = l_req
                    curr += timedelta(days=1)
    except Exception as e:
        logger.warning("Error fetching biometric/leave details for employee %s: %s", employee.employee_code, e)

    # Shared monthly Weekoff pool (see allocate_weekoff_pool): already-saved Weekoff/Weekoff
    # Halfday days have consumed their share; whatever's left is available to unsaved,
    # dynamically-approved leave requests encountered below, in date order.
    consumed_units = sum(
        2 if att.status == AttendanceStatus.weekoff
        else 1 if att.status == AttendanceStatus.weekoff_halfday
        else 0
        for att in saved_records.values()
    )
    remaining_units = max(0, WEEKOFF_POOL_UNITS_PER_MONTH - consumed_units)

    results = []
    from datetime import datetime
    for day in range(first_active_date.day, total_days + 1):
        d = date(year, month, day)
        saved = saved_records.get(d)
        bio = biometric_records.get(d)
        leave = approved_leaves.get(d)
        rec_id = saved.id if saved else None

        # Determine effective status. The company's configured weekly off day
        # always wins, even over a previously saved record - this keeps the
        # preview in sync if the company's weekly-off config changes.
        if d.weekday() in weekly_off_weekdays:
            status = AttendanceStatus.company_week_off
        elif saved:
            status = saved.status
        elif leave:
            if leave.request_type == 'PERMISSION':
                status = AttendanceStatus.permission
            elif leave.request_type == 'HALF_DAY':
                if remaining_units >= 1:
                    status = AttendanceStatus.weekoff_halfday
                    remaining_units -= 1
                else:
                    status = AttendanceStatus.half_day
            else:
                if remaining_units >= 2:
                    status = AttendanceStatus.weekoff
                    remaining_units -= 2
                else:
                    status = AttendanceStatus.leave
            rec_id = None
        elif bio:
            if bio.status == 'HALF_DAY':
                status = AttendanceStatus.half_day
            elif bio.status in ('PRESENT', 'LATE'):
                status = AttendanceStatus.present
            elif bio.status == 'ABSENT':
                status = AttendanceStatus.leave
            else:
                status = AttendanceStatus.present
            rec_id = None
        else:
            status = AttendanceStatus.present
            rec_id = None

        # Compute duration and biometric formatting
        check_in_str = bio.check_in.strftime("%I:%M %p") if (bio and bio.check_in) else None
        check_out_str = bio.check_out.strftime("%I:%M %p") if (bio and bio.check_out) else None
        duration_hrs = None
        is_late = False

        if bio:
            # bio.status is already computed at punch-in time against the correct cutoff
            # (company default, or the employee's own shift_start_time when the company
            # has enabled per-employee shift timing) - trust it rather than re-deriving
            # a separate hardcoded 10 AM threshold here, which would ignore both.
            is_late = bio.status == 'LATE'
            if bio.check_in and bio.check_out:
                t1 = datetime.combine(d, bio.check_in)
                t2 = datetime.combine(d, bio.check_out)
                duration_hrs = round(max(0.0, (t2 - t1).total_seconds() / 3600.0), 2)

        results.append({
            "id": rec_id,
            "employee_id": employee.id,
            "date": d,
            "status": status,
            "check_in": check_in_str,
            "check_out": check_out_str,
            "duration_hours": duration_hrs,
            "is_late": is_late,
            "biometric_status": bio.status if bio else None,
            "leave_type": leave.request_type if leave else None,
            "distance_meters": round(bio.distance_meters, 1) if (bio and bio.distance_meters is not None) else None,
        })

    return results


def get_attendance_readiness(user: User, month: int, year: int) -> list[dict]:
    """Return saved-day coverage for each active employee in the selected month."""
    from django.db.models import Count

    total_days = calendar.monthrange(year, month)[1]
    start_date = date(year, month, 1)
    end_date = date(year, month, total_days)
    counts = dict(
        Attendance.objects.filter(
            user=user, date__range=(start_date, end_date), employee__user=user,
            date__gte=F("employee__date_of_joining"),
        ).values("employee_id").annotate(days=Count("date")).values_list("employee_id", "days")
    )
    results = []
    for employee in Employee.objects.filter(user=user, is_active=True):
        eligible = employee.date_of_joining <= end_date
        expected_days = (end_date - max(start_date, employee.date_of_joining)).days + 1 if eligible else 0
        results.append({
            "employee_id": employee.id,
            "recorded_days": counts.get(employee.id, 0),
            "total_days": expected_days,
            "complete": eligible and counts.get(employee.id, 0) == expected_days,
            "eligible": eligible,
        })
    return results


def has_complete_attendance(user: User, employee_id: int, month: int, year: int) -> bool:
    total_days = calendar.monthrange(year, month)[1]
    start_date = date(year, month, 1)
    end_date = date(year, month, total_days)
    try:
        employee = Employee.objects.get(id=employee_id, user=user)
    except Employee.DoesNotExist:
        return False
    if employee.date_of_joining > end_date:
        return False
    first_active_date = max(start_date, employee.date_of_joining)
    expected_days = (end_date - first_active_date).days + 1
    return Attendance.objects.filter(
        user=user,
        employee_id=employee_id,
        date__range=(first_active_date, end_date),
    ).count() == expected_days


def get_leave_count(
    db, user: User, employee_id: int, month: int, year: int
) -> int:
    """Count full leave days for an employee in a given month."""
    total_days = calendar.monthrange(year, month)[1]
    start_date = date(year, month, 1)
    end_date = date(year, month, total_days)

    return Attendance.objects.filter(
        employee_id=employee_id,
        user=user,
        date__range=(start_date, end_date),
        date__gte=F("employee__date_of_joining"),
        status=AttendanceStatus.leave
    ).count()


def get_half_day_count(
    db, user: User, employee_id: int, month: int, year: int
) -> int:
    """Count half day leaves for an employee in a given month."""
    total_days = calendar.monthrange(year, month)[1]
    start_date = date(year, month, 1)
    end_date = date(year, month, total_days)

    return Attendance.objects.filter(
        employee_id=employee_id,
        user=user,
        date__range=(start_date, end_date),
        date__gte=F("employee__date_of_joining"),
        status=AttendanceStatus.half_day
    ).count()


def get_permission_count(
    db, user: User, employee_id: int, month: int, year: int
) -> int:
    """Count permission days for an employee in a given month."""
    total_days = calendar.monthrange(year, month)[1]
    start_date = date(year, month, 1)
    end_date = date(year, month, total_days)

    return Attendance.objects.filter(
        employee_id=employee_id,
        user=user,
        date__range=(start_date, end_date),
        date__gte=F("employee__date_of_joining"),
        status=AttendanceStatus.permission
    ).count()


def get_weekoff_count(
    db, user: User, employee_id: int, month: int, year: int
) -> int:
    """Count weekoff days for an employee in a given month."""
    total_days = calendar.monthrange(year, month)[1]
    start_date = date(year, month, 1)
    end_date = date(year, month, total_days)

    return Attendance.objects.filter(
        employee_id=employee_id,
        user=user,
        date__range=(start_date, end_date),
        date__gte=F("employee__date_of_joining"),
        status=AttendanceStatus.weekoff
    ).count()


def get_weekoff_halfday_count(
    db, user: User, employee_id: int, month: int, year: int
) -> int:
    """Count weekoff half days for an employee in a given month."""
    total_days = calendar.monthrange(year, month)[1]
    start_date = date(year, month, 1)
    end_date = date(year, month, total_days)

    return Attendance.objects.filter(
        employee_id=employee_id,
        user=user,
        date__range=(start_date, end_date),
        date__gte=F("employee__date_of_joining"),
        status=AttendanceStatus.weekoff_halfday
    ).count()


def get_company_week_off_count(
    db, user: User, employee_id: int, month: int, year: int
) -> int:
    """Count structural company weekly-off days (e.g. every Sunday) for an employee in a given month."""
    total_days = calendar.monthrange(year, month)[1]
    start_date = date(year, month, 1)
    end_date = date(year, month, total_days)

    return Attendance.objects.filter(
        employee_id=employee_id,
        user=user,
        date__range=(start_date, end_date),
        date__gte=F("employee__date_of_joining"),
        status=AttendanceStatus.company_week_off
    ).count()


def calculate_leave_deduction(basic_salary: float, effective_leave_days: float, month: int, year: int) -> float:
    """Calculate salary deduction based on effective leave days (1.0 for full leave, 0.5 for half day, 0.25 for permission)."""
    total_days = calendar.monthrange(year, month)[1]
    if effective_leave_days <= 0:
        return 0.0
    per_day = float(basic_salary) / total_days
    return round(per_day * float(effective_leave_days), 2)


def get_all_employees_leave_summary(
    db, user: User, month: int, year: int
) -> list[dict]:
    """Get leave summary for all active employees for a given month with net payable amount counted from joining date."""
    from app.models.salary_slip import SalarySlip
    total_days = calendar.monthrange(year, month)[1]
    start_date = date(year, month, 1)
    end_date = date(year, month, total_days)
    employees = Employee.objects.filter(
        user=user, is_active=True, date_of_joining__lte=end_date
    ).order_by("full_name")
    permission_allowance = get_permission_allowance(user)

    summaries = []
    for emp in employees:
        first_active_date = max(start_date, emp.date_of_joining) if emp.date_of_joining else start_date
        active_days = (end_date - first_active_date).days + 1
        leave_days = get_leave_count(None, user, emp.id, month, year)
        half_day_days = get_half_day_count(None, user, emp.id, month, year)
        permission_days = get_permission_count(None, user, emp.id, month, year)
        weekoff_days = get_weekoff_count(None, user, emp.id, month, year)
        weekoff_halfday_days = get_weekoff_halfday_count(None, user, emp.id, month, year)
        company_week_off_days = get_company_week_off_count(None, user, emp.id, month, year)

        excess_permissions = max(0, permission_days - permission_allowance)
        effective_leave_days = (
            leave_days * 1.0 +
            half_day_days * 0.5 +
            excess_permissions * 1.0
        )
        deduction = calculate_leave_deduction(float(emp.basic_salary), effective_leave_days, month, year)

        is_joining_month = bool(emp.date_of_joining and emp.date_of_joining > start_date)
        proration = (active_days / total_days) if is_joining_month and total_days > 0 else 1.0

        # Check existing salary slip or calculate on the fly
        existing_slip = SalarySlip.objects.filter(
            user=user, employee_id=emp.id, month=month, year=year
        ).first()

        if existing_slip:
            gross = float(existing_slip.gross_salary)
            std_deductions = float(existing_slip.total_deductions)
            net_payable = float(existing_slip.net_pay)
        else:
            full_gross = float(
                emp.basic_salary + emp.hra + emp.conveyance_allowance + emp.medical_allowance + emp.special_allowance
            )
            full_std_deductions = float(
                emp.pf_deduction + emp.professional_tax + emp.tds + emp.esi
            )
            gross = round(full_gross * proration, 2)
            std_deductions = round(full_std_deductions * proration, 2)
            net_payable = round(max(0.0, gross - std_deductions - deduction), 2)

        summaries.append({
            "employee_id": emp.id,
            "employee_name": emp.full_name,
            "employee_code": emp.employee_code,
            "month": month,
            "year": year,
            "total_days": active_days,
            "present_days": active_days - leave_days - half_day_days - permission_days - weekoff_days - weekoff_halfday_days - company_week_off_days,
            "weekoff_days": weekoff_days,
            "weekoff_halfday_days": weekoff_halfday_days,
            "company_week_off_days": company_week_off_days,
            "leave_days": leave_days,
            "half_day_days": half_day_days,
            "permission_days": permission_days,
            "effective_leave_days": effective_leave_days,
            "leave_deduction": deduction,
            "gross_salary": gross,
            "net_payable": net_payable,
            "is_joining_month": is_joining_month,
            "date_of_joining": emp.date_of_joining.isoformat() if emp.date_of_joining else None,
        })
    return summaries
