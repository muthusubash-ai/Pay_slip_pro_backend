"""Compatibility imports for the authenticated attendance API."""
from .secure_views import (  # noqa: F401
    AttendanceHistoryView, EmployeeLoginView, EmployeeRegisterView,
    GeofenceConfigView, LeaveActionView, LookupEmployeeView,
    MarkAttendanceView, MyLeaveRequestsView, RegisteredDescriptorsView,
    SubmitLeaveRequestView, UpdateProfileView, VerifyFaceView,
)

