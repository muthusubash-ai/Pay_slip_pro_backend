# Data Models

This backend is split into two Django apps that each own their own `Employee` concept:

- **`app`** — the payroll/HR/SaaS side (company owner logs in, manages employees, salary slips, settings).
- **`attendance`** — the biometric kiosk side (a separate login system for employees to punch in/out, request leave/permission). It links back to `app.Employee` via `payroll_employee`.

Because both apps define a model literally named `Employee` (and `Attendance`), this doc always qualifies them as **payroll Employee** (`app.Employee`) vs **kiosk Employee** (`attendance.Employee`).

---

## `app` — Payroll / HR

### `User` (`app.models.user.User`)
The account that logs into the main Pay Slip Pro dashboard (company owner or HR manager). Custom `AbstractBaseUser`, table `users`.

| Field | Type | Notes |
|---|---|---|
| `email` | EmailField, unique | Login identifier (`USERNAME_FIELD`). |
| `password` | CharField (db column `hashed_password`) | Hashed via `app.auth.jwt_handler.hash_password`. |
| `full_name` | CharField | |
| `role` | CharField, choices `admin` / `hr_manager` | Default `hr_manager`. |
| `is_active` | BooleanField | |
| `plan` | CharField | `starter` / `professional` / `enterprise`. Gates features via `require_minimum_plan`. |
| `plan_expires_at` | DateTimeField, nullable | `is_plan_expired` property checks this. |
| `phone` | CharField, nullable | |
| `auth_provider` | CharField | `local` or `google`. |
| `google_id` | CharField, nullable, unique | Set for Google OAuth accounts. |
| `admin_password` | CharField, nullable | **Separate** password hash used only for Django Admin (`/admin/`) login, so admin creds are independent of the app login. Checked by `DjangoAdminAuthBackend`. |
| `auth_version` | PositiveIntegerField | Bumped to invalidate all existing JWTs for this user (e.g. on password change). |
| `is_platform_admin` | BooleanField | Grants Django staff/superuser rights (`is_staff`/`is_superuser` properties derive from this + `is_active`). |
| `notification_email` | EmailField, nullable | Where HR-facing operational emails (leave/permission requests, missed punch-out alerts) are sent. Falls back to `email` via the `effective_notification_email` property when blank — lets the login inbox differ from the inbox HR actually watches. |

Related (reverse FK): `company` (one `Company`), `employees` (many `app.Employee`), `salary_slips`, `payments`, `refresh_tokens`, `salary_slip_templates`.

### `Company` (`app.models.company.Company`)
One row per `User` (`OneToOneField`), table `companies`. Holds branding, statutory details, and the biometric kiosk's geofence/shift-timing configuration.

| Field | Type | Notes |
|---|---|---|
| `company_name` | CharField | |
| `logo_url` / `logo_data` | CharField / TextField, nullable | `logo_data` is the base64-encoded logo actually used on slips/kiosk; `logo_url` is legacy/unused in practice. |
| `primary_color` | CharField(7) | Hex color auto-extracted from the uploaded logo. |
| `address`, `city`, `state`, `zip_code` | nullable | |
| `pay_day` | IntegerField, default 1 | Day of month slips are due. **Validated 1–31** at the serializer level. |
| `financial_year_start` | IntegerField, default 4 | Month number. **Validated 1–12**. |
| `pf_number`, `tan_number` | CharField, nullable | |
| `office_lat`, `office_lng` | FloatField, default `8.7892563` / `78.117146` | Geofence center for biometric punches. Serializer validates lat ∈ [-90,90], lng ∈ [-180,180]. |
| `allowed_radius_meters` | IntegerField, default 70 | Punch must be within this radius. Validated 1–50000. |
| `weekly_off_days` | JSONField (list of int), default `[]` | `date.weekday()` convention: Monday=0 … Sunday=6. The company's standing weekly off — always wins, never consumes the monthly weekoff pool. |
| `permission_days_per_month` | IntegerField, default 3 | Free permission requests per month before a 1-day deduction kicks in. Validated 0–31. |
| `office_timing` | CharField, default `"09:30 AM - 06:00 PM"` | Human-readable label, kept in sync with the two fields below. |
| `office_start_time` / `office_end_time` | CharField "HH:MM", default `09:30` / `18:00` | Company-wide default late-cutoff / checkout boundary. |
| `enable_employee_shift_timing` | BooleanField, default `False` | When on, `attendance.Employee.shift_start_time`/`shift_end_time` override the company default for that employee (see `effective_shift_times()` in `attendance/secure_views.py`). |

### `Employee` ("payroll Employee", `app.models.employee.Employee`)
Table `employees`. The HR-managed employee record — salary components, bank details, and the config used by the biometric side.

| Field | Type | Notes |
|---|---|---|
| `user` | FK → `User` | Owning company. `unique_together = (user, employee_code)`. |
| `employee_code`, `full_name`, `email`, `phone` | | `email` is prefixed `deactivated_<id>_<email>` on deactivation to free it up for an active employee. |
| `department`, `designation` | nullable | |
| `date_of_joining` | DateField | Salary slips / attendance can't predate this. |
| `bank_account_number`, `bank_name`, `ifsc_code`, `pan_number` | nullable | |
| `basic_salary`, `hra`, `conveyance_allowance`, `medical_allowance`, `special_allowance` | Decimal(12,2), default 0 | Earnings components. |
| `pf_deduction`, `professional_tax`, `tds`, `esi` | Decimal(12,2), default 0 | Deduction components. |
| `is_active` | BooleanField, default `True` | `False` = deactivated (soft-delete). |
| `shift_start_time` / `shift_end_time` | CharField "HH:MM", nullable | Per-employee override, only applied when `Company.enable_employee_shift_timing` is on. |
| `gender` | CharField, choices `MALE`/`FEMALE`, nullable | Optional — sanity-checks the live face against the employee's recorded gender during biometric registration (client-side `face-api.js` age/gender model). Blank skips the check entirely. |
| `deactivated_at` | DateTimeField, nullable | Set when `is_active` flips to `False`. A deactivated employee whose `deactivated_at` is **30+ days old** (`DEACTIVATED_RETENTION_DAYS`) is **permanently purged** (cascades to attendance/salary-slip/leave data) the next time the employee list loads. HR can also delete immediately via the explicit "Delete Permanently" action. Cleared on reactivation. |

Related (reverse FK): `salary_slips` (many `SalarySlip`), `attendance_account` (one `attendance.Employee`, via that model's `payroll_employee`).

### `SalarySlip` (`app.models.salary_slip.SalarySlip`)
Table `salary_slips`. One slip per employee per month (`unique_together = (employee, month, year)`).

| Field | Type | Notes |
|---|---|---|
| `user` | FK → `User` | Owning company (denormalized for query convenience). |
| `employee` | FK → payroll `Employee` | |
| `month`, `year` | IntegerField | |
| `basic_salary`, `hra`, `conveyance_allowance`, `medical_allowance`, `special_allowance` | Decimal(12,2) | Snapshotted from the employee at generation time. |
| `gross_salary` | Decimal(12,2) | Sum of the above. |
| `pf_deduction`, `professional_tax`, `tds`, `esi` | Decimal(12,2), default 0 | Snapshotted deductions. |
| `total_deductions` | Decimal(12,2) | |
| `leave_days` | IntegerField, default 0 | Effective leave days counted against this month (full leave = 1.0, half-day = 0.5, excess permission = 1.0 each). |
| `leave_deduction` | Decimal(12,2), default 0 | Derived from `leave_days` × daily rate; recalculated automatically if a leave/permission request is approved or rejected after the slip exists. |
| `net_pay` | Decimal(12,2) | `gross_salary - total_deductions - leave_deduction`. |
| `status` | CharField, choices `draft`/`generated`/`sent` | Default `generated`. |
| `generated_at` | DateTimeField, auto | |
| `emailed_at` | DateTimeField, nullable | Set when successfully emailed to the employee. |

### `SalarySlipTemplate` (`app.models.salary_slip_template.SalarySlipTemplate`)
Table `salary_slip_templates`. `user`, `template_name`, `template_html`, `is_default`, `created_at`. Scaffolded for custom slip templates — **currently unused** by any view/service in the codebase.

### `Attendance` ("payroll Attendance", `app.models.attendance.Attendance`)
Table `attendance`. The **payroll-side** daily status record (separate from the kiosk's own punch log below) — this is what salary slip generation actually reads. `unique_together = (employee, date)`.

| Field | Type | Notes |
|---|---|---|
| `user` | FK → `User` | |
| `employee` | FK → payroll `Employee` | |
| `date` | DateField | |
| `status` | CharField, choices (see `AttendanceStatus`) | `present`, `leave`, `weekoff`, `half_day`, `permission`, `weekoff_halfday`, `company_week_off`. |

`weekoff` vs `company_week_off`: `company_week_off` is the company's fixed recurring day off (`Company.weekly_off_days`) and never consumes any allowance. `weekoff`/`weekoff_halfday` are the flexible monthly pool (2 half-day units/month) that a leave/half-day request draws from before falling back to a real paid-leave deduction.

### `PaymentOrder` (`app.models.payment.PaymentOrder`)
Table `payment_orders`. Razorpay plan-upgrade payment tracking: `razorpay_order_id` (unique), `razorpay_payment_id`, `razorpay_signature`, `plan_name`, `amount` (paise), `status` (`created`/`paid`/`failed`).

### `RefreshToken` (`app.models.refresh_token.RefreshToken`)
Table `refresh_tokens`. JWT refresh-token tracking: `user`, `token` (unique), `expires_at`, `revoked`.

---

## `attendance` — Biometric Kiosk

### `Employee` ("kiosk Employee", `attendance.models.Employee`)
The employee's login identity for the kiosk (`/biometric`), completely separate auth from the main app's `User`.

| Field | Type | Notes |
|---|---|---|
| `emp_id` | CharField | Mirrors the payroll `employee_code`. |
| `payroll_employee` | OneToOneField → `app.Employee`, nullable, `CASCADE` | Links back to the HR record. Deleting the payroll employee cascades and deletes this row (and everything below). |
| `google_subject` | CharField | Set for Google-authenticated kiosk logins. |
| `full_name`, `email` (unique), `password` | | `password` hashed via Django's `make_password`; `check_password` only accepts recognized hash prefixes. |
| `designation` | CharField, default `"Employee"` | |
| `joining_date`, `phone_number` | nullable | |
| `face_encoding` | JSONField, nullable | 128-dimensional `face_recognition` (dlib) embedding, captured server-side at registration. **Never exposed back to the browser** (`RegisteredDescriptorsView` always returns 410) — punch-time verification is a server-side distance check (`math.dist`, threshold `0.58`) against this stored vector. |
| `profile_photo` | ImageField, nullable | |
| `is_active` | BooleanField, default `True` | Mirrors the payroll employee's deactivation state. |

**Registration integrity rules** (enforced in `EmployeeRegisterView`): an already-registered account (`is_active` + `password` set) can't be silently re-registered with a different face/password via a fresh invite — it's rejected with "already registered". Two different kiosk employees under the same company can't register with the same (or near-identical, distance ≤ 0.58) face.

### `ActivationInvite`
One-time registration invite, issued when HR clicks "Send Portal Invite" or creates an employee with "send invitation" on.

| Field | Type | Notes |
|---|---|---|
| `payroll_employee` | FK → `app.Employee` | |
| `digest` | CharField(64), unique | SHA-256 of the actual invite token (the raw token is never stored). |
| `email` | EmailField | |
| `expires_at` | DateTimeField | 24 hours from issue. |
| `used` | BooleanField, default `False` | Issuing a new invite for the same employee marks all their prior unused invites as used. |

### `EmployeeSession`
Kiosk login session. `employee` FK, `digest` (SHA-256 of the session token, unique), `expires_at` (12 hours from login). The raw token lives only in the `attendance_session` HttpOnly cookie.

### `Attendance` ("kiosk Attendance", `attendance.models.Attendance`)
The actual punch log — one row per employee per day (`unique_together = (employee, date)`), `date` is `auto_now_add` (always the real day the first punch happened, not settable).

| Field | Type | Notes |
|---|---|---|
| `employee` | FK → kiosk `Employee`, `related_name="attendances"` | |
| `date` | DateField, `auto_now_add` | |
| `check_in` / `check_out` | TimeField, nullable | |
| `status` | CharField, choices `PRESENT`/`LATE`/`HALF_DAY`/`ABSENT` | Decided at check-in time against `effective_shift_times()` (company default, or the employee's own shift when the company enables per-employee timing). |
| `punch_latitude`, `punch_longitude`, `distance_meters` | FloatField | Captured at check-in for the geofence audit trail. |
| `verification_photo` | ImageField, nullable | |
| `missed_checkout_notified_at` | DateTimeField, nullable | Set the first time a "forgot to punch out" HR email + employee reminder email are sent for this record (lazy detection, triggered by the Header notification poll — no cron in this project). Prevents duplicate emails on repeated polling. |
| `permission_out` / `permission_in` | TimeField, nullable | A temporary step-out/return pair under an **approved PERMISSION** leave request. The employee punches `permission_out`, then `permission_in` on return — `check_in`/`check_out` stay open the whole time. If the permission's duration would run past the shift's checkout boundary (no time left to return), the step-out punch becomes the real final `check_out` instead. Working-hours calculations subtract this gap. |

### `LeaveRequest`
| Field | Type | Notes |
|---|---|---|
| `employee` | FK → kiosk `Employee`, `related_name="leave_requests"` | |
| `request_type` | CharField, choices `SICK`/`CASUAL`/`HALF_DAY`/`PERMISSION` | |
| `start_date`, `end_date` | DateField | `PERMISSION`/`HALF_DAY` must be single-date. |
| `duration_hours` | FloatField, nullable | Only for `PERMISSION` (preset 1/2/3-hour options in the kiosk UI, 0 < hours ≤ 8). |
| `reason` | TextField | |
| `status` | CharField, choices `PENDING`/`APPROVED`/`REJECTED` | On approval: the payroll `Attendance` status for each covered date is derived (drawing from the shared monthly weekoff pool first), any existing `SalarySlip` for an affected month is recalculated, and an email is sent to the employee with the decision. On submission: an email is sent to `User.effective_notification_email` (HR). |
| `admin_remarks` | TextField, nullable | |

---

## Cross-app relationship summary

```
app.User ──1:1── app.Company
app.User ──1:N── app.Employee ──1:N── app.SalarySlip
                              │
                              └──1:1── attendance.Employee ──1:N── attendance.Attendance
                                                            ├──1:N── attendance.LeaveRequest
                                                            ├──1:N── attendance.EmployeeSession
                                                            └──(via app.Employee FK)── attendance.ActivationInvite
```

Deleting an `app.Employee` (the "Delete Permanently" action, or automatic purge 30 days after deactivation) **cascades through the entire right-hand branch** — the kiosk account, every punch record, every leave request, every session, every invite, and every salary slip are deleted with it. This is irreversible.
