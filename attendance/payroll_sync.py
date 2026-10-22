import calendar
import json
import urllib.request
import urllib.error
from datetime import datetime, date
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from .models import Employee, Attendance

def get_monthly_payroll_summary(employee, year: int, month: int):
    """Calculates monthly attendance stats, LOP penalty, payable days and day-wise audit."""
    _, num_days = calendar.monthrange(year, month)
    start_date = date(year, month, 1)
    end_date = date(year, month, num_days)

    from .models import LeaveRequest
    from datetime import timedelta
    approved_leaves = {}
    for l_req in LeaveRequest.objects.filter(employee=employee, status='APPROVED', start_date__lte=end_date, end_date__gte=start_date):
        curr = max(start_date, l_req.start_date)
        req_end = min(end_date, l_req.end_date)
        while curr <= req_end:
            approved_leaves[curr] = l_req
            curr += timedelta(days=1)

    records = Attendance.objects.filter(
        employee=employee,
        date__gte=start_date,
        date__lte=end_date
    )
    records_by_date = {att.date: att for att in records}

    present_count = 0
    late_count = 0
    half_day_count = 0
    leave_count = 0
    permission_count = 0
    day_wise_audit = []

    for day in range(1, num_days + 1):
        curr_date = date(year, month, day)
        att = records_by_date.get(curr_date)
        leave_req = approved_leaves.get(curr_date)

        if att:
            is_late = att.status == 'LATE'
            if is_late:
                late_count += 1
            else:
                present_count += 1

            duration_hrs = 0
            if att.check_in and att.check_out:
                t1 = datetime.combine(curr_date, att.check_in)
                if att.check_out < att.check_in:
                    t2 = datetime.combine(curr_date + timedelta(days=1), att.check_out)
                else:
                    t2 = datetime.combine(curr_date, att.check_out)
                gap_hrs = 0.0
                if att.permission_out and att.permission_in:
                    p1 = datetime.combine(curr_date, att.permission_out)
                    p2 = datetime.combine(curr_date, att.permission_in)
                    if p2 > p1:
                        gap_hrs = (p2 - p1).total_seconds() / 3600.0
                duration_hrs = round(max(0.0, (t2 - t1).total_seconds() / 3600.0 - gap_hrs), 2)
                if duration_hrs < 5.0 and att.status != 'LATE':
                    half_day_count += 1

            day_wise_audit.append({
                "date": curr_date.strftime("%Y-%m-%d"),
                "day_name": curr_date.strftime("%a"),
                "check_in": att.check_in.strftime("%I:%M %p") if att.check_in else None,
                "check_out": att.check_out.strftime("%I:%M %p") if att.check_out else None,
                "permission_out": att.permission_out.strftime("%I:%M %p") if att.permission_out else None,
                "permission_in": att.permission_in.strftime("%I:%M %p") if att.permission_in else None,
                "status": att.status,
                "duration_hours": duration_hrs,
                "distance_m": round(att.distance_meters, 1) if att.distance_meters else 0
            })
        elif leave_req:
            status_label = "HALF_DAY" if leave_req.request_type == "HALF_DAY" else ("PERMISSION" if leave_req.request_type == "PERMISSION" else "LEAVE")
            if leave_req.request_type == "HALF_DAY":
                half_day_count += 1
            elif leave_req.request_type == "PERMISSION":
                permission_count += 1
            else:
                leave_count += 1

            day_wise_audit.append({
                "date": curr_date.strftime("%Y-%m-%d"),
                "day_name": curr_date.strftime("%a"),
                "check_in": None,
                "check_out": None,
                "status": status_label,
                "duration_hours": leave_req.duration_hours or 0,
                "distance_m": 0
            })
        else:
            # Do not mark future dates as ABSENT or WEEKEND
            today = date.today()
            if curr_date <= today:
                is_weekend = curr_date.weekday() == 6 # Sunday only

                day_wise_audit.append({
                    "date": curr_date.strftime("%Y-%m-%d"),
                    "day_name": curr_date.strftime("%a"),
                    "check_in": None,
                    "check_out": None,
                    "status": "WEEKEND" if is_weekend else "ABSENT",
                    "duration_hours": 0,
                    "distance_m": 0
                })

    # Pure late count without LOP deduction penalty
    late_penalty_lop = 0
    absent_days = sum(1 for d in day_wise_audit if d["status"] == "ABSENT")
    loss_of_pay_days = absent_days
    payable_days = max(0, num_days - loss_of_pay_days)

    return {
        "emp_id": employee.emp_id,
        "employee_name": employee.full_name,
        "month": month,
        "month_name": start_date.strftime("%B"),
        "year": year,
        "calendar_days": num_days,
        "present_count": present_count,
        "late_count": late_count,
        "late_penalty_lop": late_penalty_lop,
        "half_day_count": half_day_count,
        "absent_count": absent_days,
        "loss_of_pay_days": round(loss_of_pay_days, 1),
        "payable_days": round(payable_days, 1),
        "day_wise_audit": day_wise_audit
    }
