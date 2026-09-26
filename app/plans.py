from app.exceptions import ForbiddenError


PLAN_STARTER = "starter"
PLAN_PROFESSIONAL = "professional"
PLAN_ENTERPRISE = "enterprise"

PLAN_LEVELS = {
    PLAN_STARTER: 0,
    PLAN_PROFESSIONAL: 1,
    PLAN_ENTERPRISE: 2,
}

EMPLOYEE_LIMITS = {
    PLAN_STARTER: 3,
    PLAN_PROFESSIONAL: 10,
    PLAN_ENTERPRISE: None,
}


def get_user_plan(user) -> str:
    plan = getattr(user, "plan", PLAN_STARTER)
    return plan if plan in PLAN_LEVELS else PLAN_STARTER


def has_minimum_plan(user, minimum_plan: str) -> bool:
    return PLAN_LEVELS[get_user_plan(user)] >= PLAN_LEVELS[minimum_plan]


def require_minimum_plan(user, minimum_plan: str, feature_name: str) -> None:
    if has_minimum_plan(user, minimum_plan):
        return
    display_plan = minimum_plan.title()
    raise ForbiddenError(f"{feature_name} requires the {display_plan} plan or higher.")


def get_employee_limit(user) -> int | None:
    return EMPLOYEE_LIMITS[get_user_plan(user)]
