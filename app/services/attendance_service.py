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
    weekoff_dates: list[date] | None = None,
    half_day_dates: list[date] | None = None,
    permission_dates: list[date] | None = None,
) -> list[Attendance]:
    """Mark leave, half-day, permission and weekoff dates for an employee in a given month."""
    try:
        employee = Employee.objects.get(id=employee_id, user=user)
    except Employee.DoesNotExist:
        raise NotFoundError("Employee")

    total_days = calendar.monthrange(year, month)[1]
    start_date = date(year, month, 1)
    end_date = date(year, month, total_days)
    if end_date < employee.date_of_joining:
        raise BadRequestError(
            f"Attendance cannot be saved before {employee.full_name}'s joining date ({employee.date_of_joining})."
        )
    first_active_date = max(start_date, employee.date_of_joining)
    selected_dates = set(leave_dates) | set(weekoff_dates or []) | set(half_day_dates or []) | set(permission_dates or [])
    if any(day < first_active_date or day > end_date for day in selected_dates):
        raise BadRequestError("Attendance dates must be on or after the employee's joining date in the selected month.")

    with transaction.atomic():
        # Delete existing records for this employee/month
        Attendance.objects.filter(
            employee_id=employee_id,
            date__range=(start_date, end_date)
        ).delete()

        leave_set = set(leave_dates)
        weekoff_set = set(weekoff_dates or [])
        half_day_set = set(half_day_dates or [])
        permission_set = set(permission_dates or [])

        records = []
        for day in range(first_active_date.day, total_days + 1):
            d = date(year, month, day)
            if d in leave_set:
                status = AttendanceStatus.leave
            elif d in half_day_set:
                status = AttendanceStatus.half_day
            elif d in permission_set:
                status = AttendanceStatus.permission
            elif d in weekoff_set:
                status = AttendanceStatus.weekoff
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
        # Full day leave = 1.0 day
        # Half day leave = 0.5 day
        # Permission = 0.25 day
        effective_leave_days = (
            len(leave_set) * 1.0 +
            len(half_day_set) * 0.5 +
            len(permission_set) * 0.25
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
) -> list[Attendance]:
    """Get all attendance records for an employee in a month."""
    try:
        employee = Employee.objects.get(id=employee_id, user=user)
    except Employee.DoesNotExist:
        raise NotFoundError("Employee")
    total_days = calendar.monthrange(year, month)[1]
    start_date = date(year, month, 1)
    end_date = date(year, month, total_days)
    if end_date < employee.date_of_joining:
        return []

    return list(
        Attendance.objects.filter(
            employee_id=employee_id,
            user=user,
            date__range=(max(start_date, employee.date_of_joining), end_date)
        ).order_by("date")
    )


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
    """Get leave summary for all active employees for a given month with net payable amount."""
    from app.models.salary_slip import SalarySlip
    total_days = calendar.monthrange(year, month)[1]
    start_date = date(year, month, 1)
    end_date = date(year, month, total_days)
    employees = Employee.objects.filter(
        user=user, is_active=True, date_of_joining__lte=end_date
    ).order_by("full_name")

    summaries = []
    for emp in employees:
        active_days = (end_date - max(start_date, emp.date_of_joining)).days + 1
        leave_days = get_leave_count(None, user, emp.id, month, year)
        half_day_days = get_half_day_count(None, user, emp.id, month, year)
        permission_days = get_permission_count(None, user, emp.id, month, year)
        weekoff_days = get_weekoff_count(None, user, emp.id, month, year)

        effective_leave_days = (
            leave_days * 1.0 +
            half_day_days * 0.5 +
            permission_days * 0.25
        )
        deduction = calculate_leave_deduction(float(emp.basic_salary), effective_leave_days, month, year)

        # Check existing salary slip or calculate on the fly
        existing_slip = SalarySlip.objects.filter(
            user=user, employee_id=emp.id, month=month, year=year
        ).first()

        if existing_slip:
            gross = float(existing_slip.gross_salary)
            std_deductions = float(existing_slip.total_deductions)
            net_payable = round(max(0.0, gross - std_deductions - deduction), 2)
        else:
            gross = float(
                emp.basic_salary + emp.hra + emp.conveyance_allowance + emp.medical_allowance + emp.special_allowance
            )
            std_deductions = float(
                emp.pf_deduction + emp.professional_tax + emp.tds + emp.esi
            )
            net_payable = round(max(0.0, gross - std_deductions - deduction), 2)

        summaries.append({
            "employee_id": emp.id,
            "employee_name": emp.full_name,
            "employee_code": emp.employee_code,
            "month": month,
            "year": year,
            "total_days": active_days,
            "present_days": active_days - leave_days - half_day_days - permission_days - weekoff_days,
            "weekoff_days": weekoff_days,
            "leave_days": leave_days,
            "half_day_days": half_day_days,
            "permission_days": permission_days,
            "effective_leave_days": effective_leave_days,
            "leave_deduction": deduction,
            "gross_salary": gross,
            "net_payable": net_payable,
        })
    return summaries
