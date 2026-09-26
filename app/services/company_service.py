import logging

from app.models.company import Company
from app.models.user import User

logger = logging.getLogger(__name__)


def get_company(db, user: User) -> Company | None:
    try:
        return Company.objects.get(user=user)
    except Company.DoesNotExist:
        return None


def update_company(db, user: User, data) -> Company:
    if not isinstance(data, dict):
        update_data = data.model_dump(exclude_unset=True)
    else:
        update_data = data

    company = get_company(None, user)
    if not company:
        company_name = update_data.get("company_name") or "My Company"
        company = Company(user=user, company_name=company_name)
        company.save()

    for key, value in update_data.items():
        if value is not None:
            setattr(company, key, value)
            
    company.save()
    logger.info("Company settings updated for user %d", user.id)
    return company
