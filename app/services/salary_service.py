import logging
import math

from app.exceptions import BadRequestError, ConflictError, NotFoundError
from app.models.employee import Employee
from app.models.salary_slip import SalarySlip, SlipStatus
from app.models.user import User
from app.services.attendance_service import calculate_leave_deduction, get_leave_count

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

    # Auto-detect leave days from attendance records
    leave_days = get_leave_count(None, user, employee.id, month, year)
    leave_ded = calculate_leave_deduction(
        float(employee.basic_salary), leave_days, month, year
    )

    gross = (
        employee.basic_salary
        + employee.hra
        + employee.conveyance_allowance
        + employee.medical_allowance
        + employee.special_allowance
    )
    deductions = (
        employee.pf_deduction + employee.professional_tax + employee.tds + employee.esi
    )
    net = float(gross) - float(deductions) - leave_ded

    slip = SalarySlip(
        user=user,
        employee=employee,
        month=month,
        year=year,
        basic_salary=employee.basic_salary,
        hra=employee.hra,
        conveyance_allowance=employee.conveyance_allowance,
        medical_allowance=employee.medical_allowance,
        special_allowance=employee.special_allowance,
        gross_salary=gross,
        pf_deduction=employee.pf_deduction,
        professional_tax=employee.professional_tax,
        tds=employee.tds,
        esi=employee.esi,
        total_deductions=deductions,
        leave_days=leave_days,
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
