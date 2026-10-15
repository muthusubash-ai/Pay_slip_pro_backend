from django.urls import path
from .secure_views import (
    MarkAttendanceView, EmployeeRegisterView, AttendanceHistoryView, 
    GeofenceConfigView, EmployeeLoginView, VerifyFaceView, UpdateProfileView,
    SubmitLeaveRequestView, MyLeaveRequestsView, LeaveActionView, RegisteredDescriptorsView,
    LookupEmployeeView, MonthlySummaryView, SyncToPayslipProView, MeView, LogoutView, GoogleNonceView, GoogleLoginView,
    AttendanceForgotPasswordView, AttendanceResetPasswordView
)

urlpatterns = [
    path('me/', MeView.as_view()),
    path('logout/', LogoutView.as_view()),
    path('google/nonce/', GoogleNonceView.as_view()),
    path('google/login/', GoogleLoginView.as_view()),
    path('config/', GeofenceConfigView.as_view(), name='geofence-config'),
    path('geofence-config/', GeofenceConfigView.as_view(), name='geofence-config-alias'),
    path('register/', EmployeeRegisterView.as_view(), name='employee-register'),
    path('lookup-employee/', LookupEmployeeView.as_view(), name='lookup-employee'),
    path('login/', EmployeeLoginView.as_view(), name='employee-login'),
    path('forgot-password/', AttendanceForgotPasswordView.as_view(), name='attendance-forgot-password'),
    path('reset-password/', AttendanceResetPasswordView.as_view(), name='attendance-reset-password'),
    path('verify-face/', VerifyFaceView.as_view(), name='verify-face'),
    path('registered-descriptors/', RegisteredDescriptorsView.as_view(), name='registered-descriptors'),
    path('update-profile/', UpdateProfileView.as_view(), name='update-profile'),
    path('mark-attendance/', MarkAttendanceView.as_view(), name='mark-attendance'),
    path('history/', AttendanceHistoryView.as_view(), name='attendance-history'),
    path('monthly-summary/', MonthlySummaryView.as_view(), name='monthly-summary'),
    path('sync-to-payslippro/', SyncToPayslipProView.as_view(), name='sync-to-payslippro'),
    path('leave-request/', SubmitLeaveRequestView.as_view(), name='leave-request'),
    path('my-leaves/', MyLeaveRequestsView.as_view(), name='my-leaves'),
    path('leave-action/', LeaveActionView.as_view(), name='leave-action'),
]
