import logging
from datetime import datetime
from django.db import models

from app.models.employee import Employee
from app.models.salary_slip import SalarySlip
from app.models.user import User

logger = logging.getLogger(__name__)


def get_dashboard_stats(db, user: User) -> dict:
    active = Employee.objects.filter(user=user, is_active=True).count()
    total = active
    
    total_payroll_dict = Employee.objects.filter(user=user, is_active=True).aggregate(
        models.Sum("basic_salary")
    )
    total_payroll = total_payroll_dict["basic_salary__sum"] or 0
    
    # Current month salary paid (sum of net_pay for current month's salary slips)
    now = datetime.now()
    current_month_salary_dict = SalarySlip.objects.filter(
        user=user,
        month=now.month,
        year=now.year,
    ).aggregate(models.Sum("net_pay"))
    current_month_salary = current_month_salary_dict["net_pay__sum"] or 0
    
    avg_salary = float(total_payroll) / active if active > 0 else 0.0
    
    return {
        "total_employees": total,
        "active_employees": active,
        "total_payroll": float(total_payroll),
        "current_month_salary": float(current_month_salary),
        "avg_salary": avg_salary,
    }


def get_payroll_summary(db, user: User, month: int, year: int) -> dict:
    slips = SalarySlip.objects.filter(
        user=user,
        month=month,
        year=year,
    )
    
    total_gross = sum(float(s.gross_salary) for s in slips)
    total_deductions = sum(float(s.total_deductions) for s in slips)
    total_net = sum(float(s.net_pay) for s in slips)
    
    return {
        "month": month,
        "year": year,
        "total_gross": total_gross,
        "total_deductions": total_deductions,
        "total_net": total_net,
        "slip_count": len(slips),
    }


def get_department_breakdown(db, user: User) -> list[dict]:
    """Return individual employees with their department and designation."""
    employees = Employee.objects.filter(user=user, is_active=True).order_by("department", "full_name")
    
    return [
        {
            "department": emp.department or "Unassigned",
            "employee_name": emp.full_name,
            "designation": emp.designation or "N/A",
            "employee_code": emp.employee_code,
            "basic_salary": float(emp.basic_salary),
        }
        for emp in employees
    ]
