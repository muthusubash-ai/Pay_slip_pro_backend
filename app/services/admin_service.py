import logging
import math

from app.exceptions import NotFoundError
from app.models.employee import Employee
from app.models.salary_slip import SalarySlip
from app.models.user import User

logger = logging.getLogger(__name__)


def list_users(db, page: int = 1, per_page: int = 20) -> dict:
    query = User.objects.all()
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


def update_user(
    db, user_id: int, role: str | None = None, is_active: bool | None = None
) -> User:
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        raise NotFoundError("User")
        
    if role is not None:
        user.role = role
    if is_active is not None:
        user.is_active = is_active
        
    user.save()
    return user


def deactivate_user(db, user_id: int) -> User:
    return update_user(None, user_id, is_active=False)


def get_platform_stats(db) -> dict:
    total_users = User.objects.count()
    active_users = User.objects.filter(is_active=True).count()
    total_employees = Employee.objects.count()
    total_slips = SalarySlip.objects.count()
    
    return {
        "total_users": total_users,
        "active_users": active_users,
        "total_employees": total_employees,
        "total_slips": total_slips,
    }
