import logging
import math
from datetime import timedelta

from django.db.models import Q
from django.db.models.functions import Lower
from django.db import transaction
from django.utils import timezone

from app.exceptions import ConflictError, NotFoundError
from app.models.employee import Employee
from app.models.salary_slip import SalarySlip
from app.models.user import User

logger = logging.getLogger(__name__)

# A deactivated employee (and all of their cascaded attendance/salary-slip/leave
# data) is permanently deleted this many days after deactivation, unless HR
# deletes them sooner with the explicit "Delete Permanently" action.
DEACTIVATED_RETENTION_DAYS = 30


def purge_expired_deactivated_employees(user: User) -> int:
    cutoff = timezone.now() - timedelta(days=DEACTIVATED_RETENTION_DAYS)
    expired = Employee.objects.filter(user=user, is_active=False, deactivated_at__lte=cutoff)
    count = expired.count()
    if count:
        for employee in expired:
            logger.info(
                "Auto-purging deactivated employee past %s-day retention: %s (%s)",
                DEACTIVATED_RETENTION_DAYS, employee.full_name, employee.employee_code,
            )
        expired.delete()
    return count


def list_employees(
    db,
    user: User,
    page: int = 1,
    per_page: int = 20,
    search: str | None = None,
    department: str | None = None,
    sort_by: str | None = None,
    status: str | None = "active",
) -> dict:
    purge_expired_deactivated_employees(user)

    if status == "inactive":
        query = Employee.objects.filter(user=user, is_active=False)
    elif status == "all":
        query = Employee.objects.filter(user=user)
    else:
        query = Employee.objects.filter(user=user, is_active=True)

    if search:
        query = query.filter(
            Q(full_name__icontains=search)
            | Q(employee_code__icontains=search)
            | Q(email__icontains=search)
        )
    if department:
        query = query.filter(department=department)

    # Alphabetical and newest sorting
    if sort_by in ("name_asc", "alpha_asc", "az", "name"):
        query = query.order_by(Lower("full_name").asc(), "-created_at", "-id")
    elif sort_by in ("name_desc", "alpha_desc", "za"):
        query = query.order_by(Lower("full_name").desc(), "-created_at", "-id")
    elif sort_by in ("oldest", "date_asc"):
        query = query.order_by("created_at", "id")
    else:
        # Default: newest employees first so newly saved employees appear at the top
        query = query.order_by("-created_at", "-id")
        
    total = query.count()
    active_count = Employee.objects.filter(user=user, is_active=True).count()
    inactive_count = Employee.objects.filter(user=user, is_active=False).count()
    pages = math.ceil(total / per_page) if per_page > 0 else 0
    items = list(query[(page - 1) * per_page : page * per_page])
    return {
        "items": items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": pages,
        "active_count": active_count,
        "inactive_count": inactive_count,
    }


def create_employee(db, user: User, data) -> Employee:
    if not isinstance(data, dict):
        data = data.model_dump()
        
    employee_code = data.get("employee_code")
    email = str(data.get("email") or "").strip().lower()

    # Enforce uniqueness of email under this company/user
    if email:
        existing_email_emp = Employee.objects.filter(user=user, email__iexact=email, is_active=True).first()
        if existing_email_emp:
            raise ConflictError(
                f"Email '{email}' is already assigned to employee {existing_email_emp.employee_code} ({existing_email_emp.full_name}). "
                "Each employee must have a unique email address."
            )
        try:
            from attendance.models import Employee as AttendanceEmployee
            att_emp = AttendanceEmployee.objects.filter(email__iexact=email, is_active=True).first()
            if att_emp and (att_emp.payroll_employee_id or (att_emp.emp_id and att_emp.emp_id.lower() != str(employee_code).lower())):
                raise ConflictError(
                    f"Email '{email}' is already assigned to another attendance account ({att_emp.emp_id} - {att_emp.full_name}). "
                    "Each employee must have a unique email address."
                )
        except ConflictError:
            raise
        except Exception:
            pass

    existing = Employee.objects.filter(user=user, employee_code=employee_code).first()
    if existing:
        if existing.is_active:
            raise ConflictError(f"Employee code '{employee_code}' already exists")
        # Reactivate existing inactive employee with updated data
        for key, value in data.items():
            setattr(existing, key, value)
        existing.is_active = True
        existing.deactivated_at = None
        existing.save()

        # Reactivate and sync attendance module record
        try:
            from attendance.models import Employee as AttendanceEmployee
            att = AttendanceEmployee.objects.filter(payroll_employee=existing).first()
            if att:
                att.is_active = True
                if email:
                    att.email = email
                att.full_name = existing.full_name
                att.save(update_fields=['is_active', 'email', 'full_name', 'updated_at'])
        except Exception as ex:
            logger.warning("Could not sync reactivated attendance account: %s", ex)

        logger.info("Employee reactivated: %s", employee_code)
        return existing
        
    employee = Employee(user=user, **data)
    employee.save()
    if data.get("shift_start_time") or data.get("shift_end_time"):
        company = getattr(user, 'company', None)
        if company and not company.enable_employee_shift_timing:
            company.enable_employee_shift_timing = True
            company.save(update_fields=['enable_employee_shift_timing'])
    logger.info("Employee created: %s", employee_code)
    return employee


def reactivate_employee(db, user: User, employee_id: int, new_email: str | None = None) -> Employee:
    try:
        employee = Employee.objects.get(id=employee_id, user=user)
    except Employee.DoesNotExist:
        raise NotFoundError("Employee")

    if employee.is_active:
        return employee

    # Determine email to restore
    email = (new_email or "").strip().lower()
    if not email:
        curr_email = (employee.email or "").strip()
        if curr_email.startswith("deactivated_"):
            parts = curr_email.split("_", 2)
            if len(parts) == 3 and "@" in parts[2]:
                email = parts[2].lower()
            else:
                email = ""
        else:
            email = curr_email.lower()

    if not email:
        raise ConflictError("A valid email address is required to reactivate this employee.")

    # Ensure no active employee already has this email
    conflict = Employee.objects.filter(user=user, email__iexact=email, is_active=True).exclude(pk=employee.pk).first()
    if conflict:
        raise ConflictError(f"Email '{email}' is already assigned to active employee {conflict.employee_code} ({conflict.full_name}). Each employee must have a unique email address.")

    try:
        from attendance.models import Employee as AttendanceEmployee
        att_conflict = AttendanceEmployee.objects.filter(email__iexact=email, is_active=True).first()
        if att_conflict and att_conflict.payroll_employee_id and att_conflict.payroll_employee_id != employee.pk:
            raise ConflictError(f"Email '{email}' is already assigned to another active attendance account ({att_conflict.emp_id} - {att_conflict.full_name}).")
    except ConflictError:
        raise
    except Exception:
        pass

    employee.email = email
    employee.is_active = True
    employee.deactivated_at = None
    employee.save(update_fields=["is_active", "email", "deactivated_at", "updated_at"])

    # Reactivate attendance module record
    try:
        from attendance.models import Employee as AttendanceEmployee
        att = AttendanceEmployee.objects.filter(payroll_employee=employee).first()
        if att:
            att.is_active = True
            att.email = email
            att.full_name = employee.full_name
            att.save(update_fields=["is_active", "email", "full_name", "updated_at"])
    except Exception as ex:
        logger.warning("Could not reactivate attendance record: %s", ex)

    logger.info("Reactivated employee: %s (%s)", employee.full_name, employee.employee_code)
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

        new_email = str(update_data.get("email") or "").strip().lower() if "email" in update_data and update_data["email"] else None
        if new_email and new_email != (employee.email or "").strip().lower():
            existing_email_emp = Employee.objects.filter(user=user, email__iexact=new_email, is_active=True).exclude(pk=employee.pk).first()
            if existing_email_emp:
                raise ConflictError(
                    f"Email '{new_email}' is already assigned to employee {existing_email_emp.employee_code} ({existing_email_emp.full_name}). "
                    "Each employee must have a unique email address."
                )
            try:
                from attendance.models import Employee as AttendanceEmployee
                att_emp = AttendanceEmployee.objects.filter(email__iexact=new_email, is_active=True).first()
                if att_emp and att_emp.payroll_employee_id and att_emp.payroll_employee_id != employee.pk:
                    raise ConflictError(
                        f"Email '{new_email}' is already assigned to another attendance account ({att_emp.emp_id} - {att_emp.full_name}). "
                        "Each employee must have a unique email address."
                    )
            except ConflictError:
                raise
            except Exception:
                pass

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

        # Keep attendance account email in sync if present
        if new_email:
            try:
                from attendance.models import Employee as AttendanceEmployee
                att_account = AttendanceEmployee.objects.filter(payroll_employee=employee).first()
                if att_account and att_account.email.lower() != new_email:
                    att_account.email = new_email
                    att_account.save(update_fields=['email'])
            except Exception as e:
                logger.warning("Could not sync attendance account email: %s", e)

        if update_data.get("shift_start_time") or update_data.get("shift_end_time"):
            company = getattr(user, 'company', None)
            if company and not company.enable_employee_shift_timing:
                company.enable_employee_shift_timing = True
                company.save(update_fields=['enable_employee_shift_timing'])

        return employee


def delete_employee(db, user: User, employee_id: int):
    """Deactivate employee by setting is_active=False without deleting historical salary slips or attendance data."""
    employee = get_employee(db, user, employee_id)
    emp_code = employee.employee_code
    emp_name = employee.full_name
    emp_email = employee.email

    employee.is_active = False
    employee.deactivated_at = timezone.now()
    if employee.email and not employee.email.startswith("deactivated_"):
        employee.email = f"deactivated_{employee.id}_{employee.email}"
    employee.save(update_fields=["is_active", "deactivated_at", "email", "updated_at"])

    # Also deactivate associated attendance module record and release email so active employees can use it
    try:
        from attendance.models import Employee as AttendanceEmployee
        for att in AttendanceEmployee.objects.filter(payroll_employee=employee):
            att.is_active = False
            if att.email and not att.email.startswith("deactivated_"):
                att.email = f"deactivated_{att.id}_{att.email}"
            att.save(update_fields=["is_active", "email", "updated_at"])
        logger.info("Deactivated attendance module record and released email for: %s", emp_code)
    except Exception as ex:
        logger.warning("Could not deactivate attendance records: %s", ex)

    logger.info("Deactivated employee: %s (%s)", emp_name, emp_code)
    return {
        "id": employee_id,
        "employee_code": emp_code,
        "full_name": emp_name,
        "email": emp_email,
        "is_active": False,
    }


def permanent_delete_employee(db, user: User, employee_id: int):
    """Irreversibly delete a deactivated employee and everything that cascades from
    it (payroll attendance, salary slips, the attendance-kiosk account, biometric
    attendance/leave history). Only allowed once the employee has already been
    deactivated, so this is always a deliberate second step, never a one-click
    delete of a live employee."""
    employee = get_employee(db, user, employee_id)
    if employee.is_active:
        raise ConflictError("Deactivate this employee first, then permanently delete them.")

    emp_code = employee.employee_code
    emp_name = employee.full_name
    employee.delete()

    logger.info("Permanently deleted employee: %s (%s)", emp_name, emp_code)
    return {
        "id": employee_id,
        "employee_code": emp_code,
        "full_name": emp_name,
    }
