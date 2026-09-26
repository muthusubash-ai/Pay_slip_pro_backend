import calendar
import logging
from datetime import date

from app.exceptions import NotFoundError
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
) -> list[Attendance]:
    """Mark leave and weekoff dates for an employee in a given month."""
    try:
        employee = Employee.objects.get(id=employee_id, user=user)
    except Employee.DoesNotExist:
        raise NotFoundError("Employee")

    total_days = calendar.monthrange(year, month)[1]
    start_date = date(year, month, 1)
    end_date = date(year, month, total_days)

    # Delete existing records for this employee/month
    Attendance.objects.filter(
        employee_id=employee_id,
        date__range=(start_date, end_date)
    ).delete()

    leave_set = set(leave_dates)
    weekoff_set = set(weekoff_dates or [])

    records = []
    for day in range(1, total_days + 1):
        d = date(year, month, day)
        if d in leave_set:
            status = AttendanceStatus.leave
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

    return records


def get_monthly_attendance(
    db, user: User, employee_id: int, month: int, year: int
) -> list[Attendance]:
    """Get all attendance records for an employee in a month."""
    total_days = calendar.monthrange(year, month)[1]
    start_date = date(year, month, 1)
    end_date = date(year, month, total_days)

    return list(
        Attendance.objects.filter(
            employee_id=employee_id,
            user=user,
            date__range=(start_date, end_date)
        ).order_by("date")
    )


def get_leave_count(
    db, user: User, employee_id: int, month: int, year: int
) -> int:
    """Count leave days for an employee in a given month."""
    total_days = calendar.monthrange(year, month)[1]
    start_date = date(year, month, 1)
    end_date = date(year, month, total_days)

    return Attendance.objects.filter(
        employee_id=employee_id,
        user=user,
        date__range=(start_date, end_date),
        status=AttendanceStatus.leave
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
        status=AttendanceStatus.weekoff
    ).count()


def calculate_leave_deduction(basic_salary: float, leave_days: int, month: int, year: int) -> float:
    """Calculate salary deduction based on leave days only."""
    total_days = calendar.monthrange(year, month)[1]
    if leave_days <= 0:
        return 0.0
    per_day = float(basic_salary) / total_days
    return round(per_day * leave_days, 2)


def get_all_employees_leave_summary(
    db, user: User, month: int, year: int
) -> list[dict]:
    """Get leave summary for all active employees for a given month."""
    employees = Employee.objects.filter(user=user, is_active=True).order_by("full_name")

    total_days = calendar.monthrange(year, month)[1]
    summaries = []
    for emp in employees:
        leave_days = get_leave_count(None, user, emp.id, month, year)
        weekoff_days = get_weekoff_count(None, user, emp.id, month, year)
        deduction = calculate_leave_deduction(float(emp.basic_salary), leave_days, month, year)
        summaries.append({
            "employee_id": emp.id,
            "employee_name": emp.full_name,
            "employee_code": emp.employee_code,
            "month": month,
            "year": year,
            "total_days": total_days,
            "leave_days": leave_days,
            "weekoff_days": weekoff_days,
            "present_days": total_days - leave_days - weekoff_days,
            "leave_deduction": deduction,
        })
    return summaries
