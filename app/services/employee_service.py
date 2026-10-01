import logging
import math
from django.db.models import Q
from django.db import transaction

from app.exceptions import ConflictError, NotFoundError
from app.models.employee import Employee
from app.models.salary_slip import SalarySlip
from app.models.user import User

logger = logging.getLogger(__name__)


def list_employees(
    db,
    user: User,
    page: int = 1,
    per_page: int = 20,
    search: str | None = None,
    department: str | None = None,
) -> dict:
    query = Employee.objects.filter(user=user, is_active=True)
    if search:
        query = query.filter(
            Q(full_name__icontains=search)
            | Q(employee_code__icontains=search)
            | Q(email__icontains=search)
        )
    if department:
        query = query.filter(department=department)
        
    total = query.count()
    pages = math.ceil(total / per_page) if per_page > 0 else 0
    items = list(query[(page - 1) * per_page : page * per_page])
    return {
        "items": items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": pages,
    }


def create_employee(db, user: User, data) -> Employee:
    if not isinstance(data, dict):
        data = data.model_dump()
        
    employee_code = data.get("employee_code")
    if Employee.objects.filter(user=user, employee_code=employee_code).exists():
        raise ConflictError(f"Employee code '{employee_code}' already exists")
        
    employee = Employee(user=user, **data)
    employee.save()
    logger.info("Employee created: %s", employee_code)
    return employee


def get_employee(db, user: User, employee_id: int) -> Employee:
    try:
        employee = Employee.objects.get(id=employee_id, user=user)
    except Employee.DoesNotExist:
        raise NotFoundError("Employee")
    return employee


def update_employee(
    db, user: User, employee_id: int, data
) -> Employee:
    if not isinstance(data, dict):
        update_data = data.model_dump(exclude_unset=True)
    else:
        update_data = data

    with transaction.atomic():
        try:
            employee = Employee.objects.select_for_update().get(id=employee_id, user=user)
        except Employee.DoesNotExist:
            raise NotFoundError("Employee") from None

        new_joining_date = update_data.get("date_of_joining")
        if new_joining_date and new_joining_date != employee.date_of_joining:
            cutoff = max(new_joining_date, employee.date_of_joining)
            affected_slips = SalarySlip.objects.filter(user=user, employee=employee).filter(
                Q(year__lt=cutoff.year) | Q(year=cutoff.year, month__lte=cutoff.month)
            )
            if affected_slips.exists():
                raise ConflictError(
                    "Date of Joining change would make existing salary slips inconsistent. "
                    "Delete the affected salary slips through the latest joining month, then update the date."
                )

        for key, value in update_data.items():
            setattr(employee, key, value)
        employee.save()
        return employee


def delete_employee(db, user: User, employee_id: int) -> Employee:
    """Permanently delete employee and their salary slips from the database."""
    employee = get_employee(db, user, employee_id)
    employee.is_active = False
    employee.delete()
    logger.info("Permanently deleted employee: %s", employee.employee_code)
    return employee
