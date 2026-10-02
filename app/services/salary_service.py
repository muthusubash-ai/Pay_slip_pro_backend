import logging
import math

from app.exceptions import BadRequestError, ConflictError, NotFoundError
from app.models.employee import Employee
from app.models.salary_slip import SalarySlip, SlipStatus
from app.models.user import User
from app.services.attendance_service import (
    calculate_leave_deduction,
    get_leave_count,
    get_half_day_count,
    get_permission_count,
    has_complete_attendance,
)

logger = logging.getLogger(__name__)


def generate_slip_for_employee(
    db, user: User, employee: Employee, month: int, year: int
) -> SalarySlip:
    existing = SalarySlip.objects.filter(
        employee=employee,
        month=month,
        year=year,
    ).first()
    
    if existing:
        raise ConflictError(
            f"Salary slip already exists for {employee.full_name} for {month}/{year}. "
            f"A salary slip can only be generated once per month. "
            f"If you want to re-generate, you must delete the existing salary slip first."
        )

    if employee.date_of_joining:
        if year < employee.date_of_joining.year or (
            year == employee.date_of_joining.year and month < employee.date_of_joining.month
        ):
            raise BadRequestError(
                f"Cannot generate salary slip for {month}/{year}. Employee {employee.full_name} joined on {employee.date_of_joining.strftime('%d %B %Y')}. Slips can only be generated from joining month onwards."
            )

    if not has_complete_attendance(user, employee.id, month, year):
        raise BadRequestError(
            f"Save complete attendance for {employee.full_name} for {month}/{year} before generating the salary slip."
        )

    # Auto-detect leave days, half-day, and permission from attendance records
    leave_days = get_leave_count(None, user, employee.id, month, year)
    half_days = get_half_day_count(None, user, employee.id, month, year)
    permissions = get_permission_count(None, user, employee.id, month, year)
    effective_leaves = float(leave_days) * 1.0 + float(half_days) * 0.5 + float(permissions) * 0.25

    leave_ded = calculate_leave_deduction(
        float(employee.basic_salary), effective_leaves, month, year
    )

    import calendar
    from datetime import date

    total_days = calendar.monthrange(year, month)[1]
    start_date = date(year, month, 1)
    end_date = date(year, month, total_days)

    first_active_date = max(start_date, employee.date_of_joining) if employee.date_of_joining else start_date
    active_days = (end_date - first_active_date).days + 1
    is_joining_month = bool(employee.date_of_joining and employee.date_of_joining > start_date)
    proration = (active_days / total_days) if is_joining_month and total_days > 0 else 1.0

    basic = round(float(employee.basic_salary) * proration, 2)
    hra = round(float(employee.hra) * proration, 2)
    conveyance = round(float(employee.conveyance_allowance) * proration, 2)
    medical = round(float(employee.medical_allowance) * proration, 2)
    special = round(float(employee.special_allowance) * proration, 2)
    gross = round(basic + hra + conveyance + medical + special, 2)

    pf = round(float(employee.pf_deduction) * proration, 2)
    pt = round(float(employee.professional_tax) * proration, 2)
    tds = round(float(employee.tds) * proration, 2)
    esi = round(float(employee.esi) * proration, 2)
    deductions = round(pf + pt + tds + esi, 2)

    net = round(max(0.0, gross - deductions - leave_ded), 2)

    slip = SalarySlip(
        user=user,
        employee=employee,
        month=month,
        year=year,
        basic_salary=basic,
        hra=hra,
        conveyance_allowance=conveyance,
        medical_allowance=medical,
        special_allowance=special,
        gross_salary=gross,
        pf_deduction=pf,
        professional_tax=pt,
        tds=tds,
        esi=esi,
        total_deductions=deductions,
        leave_days=int(round(effective_leaves)),
        leave_deduction=leave_ded,
        net_pay=net,
        status=SlipStatus.generated,
    )
    slip.save()
    return slip


def generate_bulk_slips(
    db, user: User, month: int, year: int
) -> list[SalarySlip]:
    employees = Employee.objects.filter(user=user, is_active=True)
    slips = []
    for emp in employees:
        if emp.date_of_joining:
            if year < emp.date_of_joining.year or (
                year == emp.date_of_joining.year and month < emp.date_of_joining.month
            ):
                continue

        existing = SalarySlip.objects.filter(
            employee=emp,
            month=month,
            year=year,
        ).exists()
        
        if not existing:
            if has_complete_attendance(user, emp.id, month, year):
                slip = generate_slip_for_employee(None, user, emp, month, year)
                slips.append(slip)
            
    logger.info("Generated %d salary slips for %d/%d", len(slips), month, year)
    return slips


def list_slips(
    db,
    user: User,
    page: int = 1,
    per_page: int = 20,
    month: int | None = None,
    year: int | None = None,
    employee_id: int | None = None,
) -> dict:
    query = SalarySlip.objects.filter(user=user).select_related("employee")
    if month:
        query = query.filter(month=month)
    if year:
        query = query.filter(year=year)
    if employee_id:
        query = query.filter(employee_id=employee_id)

    total = query.count()
    pages = math.ceil(total / per_page) if per_page > 0 else 0
    items = list(query.order_by("-year", "-month")[(page - 1) * per_page : page * per_page])
    return {
        "items": items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": pages,
    }


def get_slip(db, user: User, slip_id: int) -> SalarySlip:
    try:
        slip = SalarySlip.objects.select_related("employee").get(id=slip_id, user=user)
    except SalarySlip.DoesNotExist:
        raise NotFoundError("Salary slip")
    return slip


def delete_slip(db, user: User, slip_id: int) -> None:
    """Delete a salary slip regardless of status."""
    slip = get_slip(None, user, slip_id)
    slip.delete()
    logger.info("Deleted salary slip #%d for employee %s", slip_id, slip.employee.employee_code)
