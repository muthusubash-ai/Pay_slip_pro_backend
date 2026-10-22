import logging
import smtplib
import ssl
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from django.conf import settings

from app.services.pdf_service import MONTH_NAMES

logger = logging.getLogger(__name__)


def _send_email(to_email: str, subject: str, html_body: str) -> bool:
    """Send a generic HTML email."""
    if not settings.SMTP_USER or not settings.SMTP_PASSWORD:
        logger.warning("SMTP not configured, skipping email to %s", to_email)
        return False

    msg = MIMEMultipart()
    msg["From"] = f"{settings.APP_NAME} <{settings.SMTP_USER}>"
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(html_body, "html"))

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=30) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.send_message(msg)
        logger.info("Email sent to %s: %s", to_email, subject)
        return True
    except smtplib.SMTPAuthenticationError:
        logger.error("SMTP authentication failed.")
        return False
    except Exception:
        logger.exception("Error sending email to %s", to_email)
        return False


def send_password_reset_email(to_email: str, reset_code: str) -> bool:
    """Send password reset code to user via email."""
    html_body = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <div style="background: #000000; color: white; padding: 20px; text-align: center; border-radius: 8px 8px 0 0;">
            <h2 style="margin: 0;">Password Reset</h2>
        </div>
        <div style="padding: 20px; border: 1px solid #ddd; border-top: none; border-radius: 0 0 8px 8px;">
            <p>You requested a password reset. Use the code below to reset your password:</p>
            <div style="background: #f5f5f5; border: 2px solid #000; border-radius: 8px; padding: 20px; text-align: center; margin: 20px 0;">
                <span style="font-size: 32px; font-weight: bold; letter-spacing: 6px; color: #000;">{reset_code}</span>
            </div>
            <p>This code expires in <strong>15 minutes</strong>.</p>
            <p>If you did not request this, please ignore this email.</p>
        </div>
        <p style="font-size: 11px; color: #999; text-align: center; margin-top: 10px;">
            This is an automated email. Please do not reply directly.
        </p>
    </div>
    """
    return _send_email(to_email, "Password Reset Code", html_body)


def send_salary_slip_email(
    to_email: str,
    employee_name: str,
    month: int,
    year: int,
    pdf_bytes: bytes,
    company_name: str = "",
) -> bool:
    """Send salary slip PDF to employee via email.

    Args:
        to_email: Employee's email address.
        employee_name: Employee's full name for the greeting.
        month: Salary slip month (1-12).
        year: Salary slip year.
        pdf_bytes: Generated PDF content.
        company_name: Company name for the email body.

    Returns:
        True if email sent successfully, False otherwise.
    """
    # Validate SMTP configuration
    if not settings.SMTP_USER or not settings.SMTP_PASSWORD:
        logger.warning("SMTP not configured, skipping email to %s", to_email)
        return False

    # Validate email address format
    if not to_email or "@" not in to_email:
        logger.warning("Invalid email address: %s", to_email)
        return False

    month_name = MONTH_NAMES[month] if 1 <= month <= 12 else str(month)
    sender_name = company_name or settings.APP_NAME

    # Build the email message
    msg = MIMEMultipart()
    msg["From"] = f"{sender_name} <{settings.SMTP_USER}>"
    msg["To"] = to_email
    msg["Subject"] = f"Salary Slip - {month_name} {year}"

    # Professional HTML email body
    html_body = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <div style="background: #1e3a5f; color: white; padding: 20px; text-align: center; border-radius: 8px 8px 0 0;">
            <h2 style="margin: 0;">{sender_name}</h2>
        </div>
        <div style="padding: 20px; border: 1px solid #ddd; border-top: none; border-radius: 0 0 8px 8px;">
            <p>Dear <strong>{employee_name}</strong>,</p>
            <p>Please find attached your salary slip for <strong>{month_name} {year}</strong>.</p>
            <p>If you have any questions regarding your salary, please contact the HR department.</p>
            <br>
            <p>Best regards,<br><strong>HR Department</strong><br>{sender_name}</p>
        </div>
        <p style="font-size: 11px; color: #999; text-align: center; margin-top: 10px;">
            This is an automated email. Please do not reply directly.
        </p>
    </div>
    """
    msg.attach(MIMEText(html_body, "html"))

    # Attach the PDF with proper naming
    emp_name_clean = employee_name.replace(" ", "_")
    pdf_filename = f"{emp_name_clean}_SalarySlip_{month_name}{year}.pdf"
    attachment = MIMEApplication(pdf_bytes, _subtype="pdf")
    attachment.add_header(
        "Content-Disposition", "attachment", filename=pdf_filename
    )
    msg.attach(attachment)

    # Send the email via SMTP
    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=30) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.send_message(msg)
        logger.info("Salary slip email sent to %s for %s %s", to_email, month_name, year)
        return True
    except smtplib.SMTPAuthenticationError:
        logger.error("SMTP authentication failed. Check SMTP_USER and SMTP_PASSWORD.")
        return False
    except smtplib.SMTPRecipientsRefused:
        logger.error("Recipient refused: %s", to_email)
        return False
    except smtplib.SMTPException:
        logger.exception("SMTP error sending email to %s", to_email)
        return False
    except Exception:
        logger.exception("Unexpected error sending email to %s", to_email)
        return False


def send_employee_registration_invitation_email(
    to_email: str,
    employee_name: str,
    employee_code: str,
    portal_url: str,
    company_name: str = "",
    invitation_token: str = "",
) -> bool:
    """Send Biometric & Attendance portal onboarding invitation email to employee."""
    if not to_email or "@" not in to_email:
        logger.warning("Invalid email address for invitation: %s", to_email)
        return False

    sender_name = company_name or getattr(settings, "APP_NAME", "Pay Slip Pro")
    subject = f"Welcome to {sender_name} - Biometric & Attendance Portal Registration"

    import urllib.parse
    base_portal = portal_url.split('?')[0].rstrip('/')
    if not invitation_token:
        return False
    registration_url = f"{base_portal}?tab=onboard&invite={urllib.parse.quote(invitation_token)}#invite={urllib.parse.quote(invitation_token)}"
    from html import escape
    sender_name, employee_name, employee_code, to_email = (
        escape(str(value)) for value in (sender_name, employee_name, employee_code, to_email)
    )
    registration_url = escape(registration_url, quote=True)

    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8">
      <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f8fafc; margin: 0; padding: 24px; color: #1e293b; }}
        .card {{ max-width: 580px; margin: 0 auto; background-color: #ffffff; border-radius: 16px; overflow: hidden; border: 1px solid #e2e8f0; box-shadow: 0 4px 14px rgba(0,0,0,0.06); }}
        .header {{ background: linear-gradient(135deg, #4f46e5 0%, #3b82f6 100%); color: #ffffff; padding: 28px 24px; text-align: center; }}
        .body {{ padding: 28px 24px; }}
        .badge-box {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 12px; padding: 16px 20px; margin: 20px 0; }}
        .btn {{ display: inline-block; background: linear-gradient(135deg, #4f46e5 0%, #3b82f6 100%); color: #ffffff !important; text-decoration: none; padding: 14px 28px; border-radius: 12px; font-weight: 800; font-size: 14px; box-shadow: 0 4px 12px rgba(79,70,229,0.3); }}
        .footer {{ background: #f8fafc; border-top: 1px solid #e2e8f0; padding: 14px; text-align: center; font-size: 11px; color: #94a3b8; }}
      </style>
    </head>
    <body>
      <div class="card">
        <div class="header">
          <h1 style="margin: 0; font-size: 22px; font-weight: 800;">{sender_name}</h1>
          <p style="margin: 4px 0 0 0; font-size: 13px; opacity: 0.95;">Attendance & Biometric Portal Registration</p>
        </div>
        <div class="body">
          <p style="margin-top: 0; font-size: 15px;">Dear <strong>{employee_name}</strong>,</p>
          <p style="font-size: 14px; color: #475569; line-height: 1.6;">
            Welcome to <strong>{sender_name}</strong>! You have been registered in our employee management system.
            Your profile details have already been prepared. Please complete your registration by capturing your biometric face photo and creating your password.
          </p>

          <div class="badge-box">
            <p style="margin: 0 0 10px 0; font-size: 11px; font-weight: 800; text-transform: uppercase; color: #64748b; letter-spacing: 0.5px;">Your Pre-Filled Employee Credentials</p>
            <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
              <tr>
                <td style="padding: 4px 0; color: #64748b;">Employee ID:</td>
                <td style="padding: 4px 0; text-align: right;"><strong style="font-family: monospace; background: #e2e8f0; padding: 2px 8px; border-radius: 6px; color: #0f172a;">{employee_code}</strong></td>
              </tr>
              <tr>
                <td style="padding: 4px 0; color: #64748b;">Registered Email:</td>
                <td style="padding: 4px 0; text-align: right;"><strong style="color: #0f172a;">{to_email}</strong></td>
              </tr>
            </table>
          </div>

          <div style="text-align: center; margin: 28px 0 20px 0;">
            <a href="{registration_url}" target="_blank" class="btn">
              Set Up Biometric & Attendance Portal 🚀
            </a>
          </div>

          <p style="font-size: 12px; color: #94a3b8; text-align: center; margin: 12px 0 24px 0;">
            Or open this link directly in your browser: <br>
            <a href="{registration_url}" style="color: #4f46e5; word-break: break-all;">{registration_url}</a>
          </p>

          <hr style="border: none; border-top: 1px solid #f1f5f9; margin: 20px 0;">
          <p style="font-size: 13px; color: #64748b; margin-bottom: 0; line-height: 1.5;">
            Best regards,<br>
            <strong>HR & Administration Team</strong><br>
            {sender_name}
          </p>
        </div>
        <div class="footer">
          This is an automated invitation email from {sender_name}. Please do not reply directly.
        </div>
      </div>
    </body>
    </html>
    """
    return _send_email(to_email, subject, html_body)


def send_leave_request_notification_email(
    to_email: str,
    employee_name: str,
    employee_email: str,
    request_type: str,
    start_date: str,
    end_date: str,
    duration_hours: float | None,
    reason: str,
    request_id: int,
    company_name: str = "",
    base_api_url: str = "http://localhost:8000",
) -> bool:
    """Send leave request approval email notification to MD/Admin."""
    if not to_email or "@" not in to_email:
        logger.warning("Invalid admin email for leave notification: %s", to_email)
        return False

    sender_name = company_name or getattr(settings, "APP_NAME", "Pavishna Tech Solutions")
    type_labels = {
        'SICK': 'Sick Leave',
        'CASUAL': 'Casual Leave',
        'HALF_DAY': 'Half Day Leave',
        'PERMISSION': 'Permission Request'
    }
    type_label = type_labels.get(request_type.upper(), request_type)
    subject = f"🔔 Leave Request - {employee_name} ({type_label})"

    # Format duration and request badge colors
    req_upper = request_type.upper()
    if req_upper == 'PERMISSION':
        duration_str = f"{duration_hours or 2} Hours"
        badge_bg = '#3b1d54'
        badge_color = '#d8b4fe'
        badge_border = '#7e22ce'
    elif req_upper == 'HALF_DAY':
        duration_str = "Half Day (0.5 Day)"
        badge_bg = '#452203'
        badge_color = '#fcd34d'
        badge_border = '#b45309'
    elif req_upper == 'SICK':
        try:
            from datetime import datetime
            d1 = datetime.strptime(start_date, '%Y-%m-%d')
            d2 = datetime.strptime(end_date, '%Y-%m-%d')
            days_count = max(1, (d2 - d1).days + 1)
            duration_str = f"{days_count} Day{'s' if days_count > 1 else ''}"
        except Exception:
            duration_str = "1 Day"
        badge_bg = '#3b1d28'
        badge_color = '#fca5a5'
        badge_border = '#b91c1c'
    else:
        try:
            from datetime import datetime
            d1 = datetime.strptime(start_date, '%Y-%m-%d')
            d2 = datetime.strptime(end_date, '%Y-%m-%d')
            days_count = max(1, (d2 - d1).days + 1)
            duration_str = f"{days_count} Day{'s' if days_count > 1 else ''}"
        except Exception:
            duration_str = "1 Day"
        badge_bg = '#1e295d'
        badge_color = '#93c5fd'
        badge_border = '#2563eb'

    from html import escape
    try:
        from datetime import datetime
        d_start = datetime.strptime(start_date, '%Y-%m-%d')
        date_param = f"&month={d_start.month}&year={d_start.year}"
    except Exception:
        date_param = ""

    frontend_base = getattr(settings, "FRONTEND_URL", "http://localhost:5173").rstrip('/')
    action_url = escape(f"{frontend_base}/attendance?leave_request={request_id}{date_param}", quote=True)
    employee_name_esc, employee_email_esc, reason_esc, sender_name_esc = (
        escape(str(value)) for value in (employee_name, employee_email, reason, sender_name)
    )
    type_label_esc, start_date_esc, end_date_esc, duration_str_esc = (
        escape(str(value)) for value in (type_label, start_date, end_date, duration_str)
    )

    html_body = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>New Leave Request</title>
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #0b0f19; margin: 0; padding: 24px 12px; color: #f1f5f9; -webkit-font-smoothing: antialiased;">
  <!-- Outer Table Wrapper for 100% email client centering -->
  <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="background-color: #0b0f19; width: 100%;">
    <tr>
      <td align="center" style="padding: 0;">
        <!-- Main Card Container -->
        <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="max-width: 460px; margin: 0 auto; background-color: #111827; border: 1px solid #1f2937; border-radius: 16px; overflow: hidden; box-shadow: 0 16px 36px rgba(0,0,0,0.5);">
          <!-- Header Banner -->
          <tr>
            <td align="center" style="background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%); padding: 24px 20px; color: #ffffff; text-align: center;">
              <div style="font-size: 21px; font-weight: 800; letter-spacing: -0.2px; line-height: 1.3; margin: 0 0 4px 0;">
                &#x1F4CB; New Leave Request
              </div>
              <div style="font-size: 13px; font-weight: 500; opacity: 0.95; color: #f3e8ff;">
                {sender_name_esc}
              </div>
            </td>
          </tr>
          <!-- Body Content -->
          <tr>
            <td style="padding: 24px 20px;">
              <div style="font-size: 15px; font-weight: 700; color: #ffffff; margin-bottom: 4px;">
                Dear MD,
              </div>
              <div style="font-size: 13px; color: #94a3b8; margin-bottom: 20px; line-height: 1.5;">
                A new leave request needs your approval:
              </div>

              <!-- Information Details Grid -->
              <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="border-collapse: separate; border-spacing: 0; background-color: #1e293b; border: 1px solid #334155; border-radius: 12px; overflow: hidden; margin-bottom: 24px;">
                <tr>
                  <td style="width: 36%; min-width: 120px; padding: 12px 14px; background-color: #162032; color: #94a3b8; font-size: 12px; font-weight: 700; border-bottom: 1px solid #334155; border-right: 1px solid #334155; vertical-align: middle; white-space: nowrap;">
                    &#x1F464;&nbsp; Employee
                  </td>
                  <td style="padding: 12px 16px; background-color: #1e293b; color: #ffffff; font-size: 13px; font-weight: 700; border-bottom: 1px solid #334155; vertical-align: middle; word-break: break-word;">
                    {employee_name_esc}
                  </td>
                </tr>
                <tr>
                  <td style="width: 36%; min-width: 120px; padding: 12px 14px; background-color: #162032; color: #94a3b8; font-size: 12px; font-weight: 700; border-bottom: 1px solid #334155; border-right: 1px solid #334155; vertical-align: middle; white-space: nowrap;">
                    &#x1F4E7;&nbsp; Email
                  </td>
                  <td style="padding: 12px 16px; background-color: #1e293b; color: #60a5fa; font-size: 13px; font-weight: 600; border-bottom: 1px solid #334155; vertical-align: middle; word-break: break-word;">
                    <a href="mailto:{employee_email_esc}" style="color: #60a5fa !important; text-decoration: none; font-weight: 600;">{employee_email_esc}</a>
                  </td>
                </tr>
                <tr>
                  <td style="width: 36%; min-width: 120px; padding: 12px 14px; background-color: #162032; color: #94a3b8; font-size: 12px; font-weight: 700; border-bottom: 1px solid #334155; border-right: 1px solid #334155; vertical-align: middle; white-space: nowrap;">
                    &#x1F4DD;&nbsp; Type
                  </td>
                  <td style="padding: 12px 16px; background-color: #1e293b; color: #ffffff; font-size: 13px; font-weight: 600; border-bottom: 1px solid #334155; vertical-align: middle;">
                    <span style="display: inline-block; background-color: {badge_bg}; color: {badge_color}; border: 1px solid {badge_border}; padding: 3px 10px; border-radius: 6px; font-size: 12px; font-weight: 700;">
                      {type_label_esc}
                    </span>
                  </td>
                </tr>
                <tr>
                  <td style="width: 36%; min-width: 120px; padding: 12px 14px; background-color: #162032; color: #94a3b8; font-size: 12px; font-weight: 700; border-bottom: 1px solid #334155; border-right: 1px solid #334155; vertical-align: middle; white-space: nowrap;">
                    &#x1F4C5;&nbsp; From
                  </td>
                  <td style="padding: 12px 16px; background-color: #1e293b; color: #ffffff; font-size: 13px; font-weight: 700; border-bottom: 1px solid #334155; vertical-align: middle;">
                    {start_date_esc}
                  </td>
                </tr>
                <tr>
                  <td style="width: 36%; min-width: 120px; padding: 12px 14px; background-color: #162032; color: #94a3b8; font-size: 12px; font-weight: 700; border-bottom: 1px solid #334155; border-right: 1px solid #334155; vertical-align: middle; white-space: nowrap;">
                    &#x1F4C5;&nbsp; To
                  </td>
                  <td style="padding: 12px 16px; background-color: #1e293b; color: #ffffff; font-size: 13px; font-weight: 700; border-bottom: 1px solid #334155; vertical-align: middle;">
                    {end_date_esc}
                  </td>
                </tr>
                <tr>
                  <td style="width: 36%; min-width: 120px; padding: 12px 14px; background-color: #162032; color: #94a3b8; font-size: 12px; font-weight: 700; border-bottom: 1px solid #334155; border-right: 1px solid #334155; vertical-align: middle; white-space: nowrap;">
                    &#x23F1;&#xFE0F;&nbsp; Days/Hours
                  </td>
                  <td style="padding: 12px 16px; background-color: #1e293b; color: #38bdf8; font-size: 13px; font-weight: 700; border-bottom: 1px solid #334155; vertical-align: middle;">
                    {duration_str_esc}
                  </td>
                </tr>
                <tr>
                  <td style="width: 36%; min-width: 120px; padding: 12px 14px; background-color: #162032; color: #94a3b8; font-size: 12px; font-weight: 700; border-right: 1px solid #334155; vertical-align: top; white-space: nowrap;">
                    &#x1F4AC;&nbsp; Reason
                  </td>
                  <td style="padding: 12px 16px; background-color: #1e293b; color: #f8fafc; font-size: 13px; font-weight: 500; line-height: 1.5; vertical-align: top; word-break: break-word;">
                    {reason_esc}
                  </td>
                </tr>
              </table>

              <!-- Action Section Header -->
              <div style="text-align: center; margin: 0 0 14px 0;">
                <span style="font-size: 13px; font-weight: 800; color: #e2e8f0; letter-spacing: 0.3px;">
                  Take Action:
                </span>
              </div>

              <!-- Two Equal Action Buttons in a Rigid Table Layout (Guaranteed 16px Gap) -->
              <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="margin: 0 auto; max-width: 380px;">
                <tr>
                  <td align="center" width="50%" style="padding: 0 8px 0 0;">
                    <a href="{action_url}" target="_blank" style="display: block; width: 100%; box-sizing: border-box; background-color: #10b981; color: #ffffff !important; text-decoration: none; padding: 13px 14px; border-radius: 10px; font-weight: 800; font-size: 13px; text-align: center; letter-spacing: 0.5px; box-shadow: 0 4px 14px rgba(16, 185, 129, 0.4);">
                      &#x2705;&nbsp; APPROVE
                    </a>
                  </td>
                  <td align="center" width="50%" style="padding: 0 0 0 8px;">
                    <a href="{action_url}" target="_blank" style="display: block; width: 100%; box-sizing: border-box; background-color: #ef4444; color: #ffffff !important; text-decoration: none; padding: 13px 14px; border-radius: 10px; font-weight: 800; font-size: 13px; text-align: center; letter-spacing: 0.5px; box-shadow: 0 4px 14px rgba(239, 68, 68, 0.4);">
                      &#x274C;&nbsp; REJECT
                    </a>
                  </td>
                </tr>
              </table>
            </td>
          </tr>
          <!-- Footer -->
          <tr>
            <td align="center" style="background-color: #0b0f19; border-top: 1px solid #1f2937; padding: 14px 20px; text-align: center; font-size: 11px; color: #64748b;">
              {sender_name_esc} &bull; HR System
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""
    return _send_email(to_email, subject, html_body)


def send_leave_decision_email(
    to_email: str,
    employee_name: str,
    request_type: str,
    start_date: str,
    end_date: str,
    status: str,
    admin_remarks: str = "",
    company_name: str = "",
) -> bool:
    """Notify the employee once HR approves or rejects their leave/permission request."""
    if not to_email or "@" not in to_email:
        logger.warning("Invalid employee email for leave decision notice: %s", to_email)
        return False

    from html import escape

    sender_name = company_name or getattr(settings, "APP_NAME", "Pay Slip Pro")
    type_labels = {
        'SICK': 'Sick Leave', 'CASUAL': 'Casual Leave',
        'HALF_DAY': 'Half Day Leave', 'PERMISSION': 'Permission Request',
    }
    type_label = type_labels.get(request_type.upper(), request_type)
    approved = status.upper() == 'APPROVED'
    subject = f"{'✅ Approved' if approved else '❌ Rejected'}: Your {type_label} Request"
    badge_bg, badge_color, badge_border = ('#064e3b', '#6ee7b7', '#059669') if approved else ('#450a0a', '#fca5a5', '#dc2626')

    employee_name_esc, type_label_esc, start_date_esc, end_date_esc, sender_name_esc, remarks_esc = (
        escape(str(v)) for v in (employee_name, type_label, start_date, end_date, sender_name, admin_remarks or '-')
    )

    html_body = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f8fafc; margin: 0; padding: 24px; color: #1e293b;">
  <div style="max-width: 460px; margin: 0 auto; background-color: #ffffff; border-radius: 16px; overflow: hidden; border: 1px solid #e2e8f0; box-shadow: 0 4px 14px rgba(0,0,0,0.06);">
    <div style="background: linear-gradient(135deg, #4f46e5 0%, #3b82f6 100%); color: #ffffff; padding: 24px 20px; text-align: center;">
      <div style="font-size: 20px; font-weight: 800;">{sender_name_esc}</div>
      <div style="font-size: 13px; opacity: 0.95; margin-top: 4px;">Leave &amp; Permission Request Update</div>
    </div>
    <div style="padding: 24px 20px;">
      <p style="margin-top: 0; font-size: 14px;">Dear <strong>{employee_name_esc}</strong>,</p>
      <p style="font-size: 13px; color: #475569; line-height: 1.6;">Your request has been reviewed:</p>
      <div style="text-align: center; margin: 16px 0;">
        <span style="display: inline-block; background-color: {badge_bg}; color: {badge_color}; border: 1px solid {badge_border}; padding: 6px 16px; border-radius: 8px; font-size: 14px; font-weight: 800;">
          {'APPROVED' if approved else 'REJECTED'}
        </span>
      </div>
      <table style="width: 100%; border-collapse: collapse; font-size: 13px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; overflow: hidden;">
        <tr><td style="padding: 10px 14px; color: #64748b; border-bottom: 1px solid #e2e8f0;">Type</td><td style="padding: 10px 14px; text-align: right; font-weight: 700; border-bottom: 1px solid #e2e8f0;">{type_label_esc}</td></tr>
        <tr><td style="padding: 10px 14px; color: #64748b; border-bottom: 1px solid #e2e8f0;">From</td><td style="padding: 10px 14px; text-align: right; font-weight: 700; border-bottom: 1px solid #e2e8f0;">{start_date_esc}</td></tr>
        <tr><td style="padding: 10px 14px; color: #64748b;">To</td><td style="padding: 10px 14px; text-align: right; font-weight: 700;">{end_date_esc}</td></tr>
      </table>
      {f'<p style="font-size: 12px; color: #64748b; margin-top: 16px;"><strong>Admin remarks:</strong> {remarks_esc}</p>' if admin_remarks else ''}
      <p style="font-size: 12px; color: #94a3b8; margin-top: 20px;">Best regards,<br><strong>HR &amp; Administration Team</strong><br>{sender_name_esc}</p>
    </div>
  </div>
</body>
</html>"""
    return _send_email(to_email, subject, html_body)


def send_missed_checkout_email(
    to_email: str, employee_name: str, date_str: str, check_in: str, company_name: str = "",
) -> bool:
    """Notify HR that an employee punched in but never punched out that day."""
    if not to_email or "@" not in to_email:
        logger.warning("Invalid HR email for missed-checkout notice: %s", to_email)
        return False

    from html import escape
    sender_name = company_name or getattr(settings, "APP_NAME", "Pay Slip Pro")
    subject = f"Missed Punch-Out: {employee_name} on {date_str}"
    employee_name_esc, date_str_esc, check_in_esc, sender_name_esc = (
        escape(str(v)) for v in (employee_name, date_str, check_in or '-', sender_name)
    )

    html_body = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f8fafc; margin: 0; padding: 24px; color: #1e293b;">
  <div style="max-width: 460px; margin: 0 auto; background-color: #ffffff; border-radius: 16px; overflow: hidden; border: 1px solid #e2e8f0; box-shadow: 0 4px 14px rgba(0,0,0,0.06);">
    <div style="background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%); color: #ffffff; padding: 24px 20px; text-align: center;">
      <div style="font-size: 20px; font-weight: 800;">{sender_name_esc}</div>
      <div style="font-size: 13px; opacity: 0.95; margin-top: 4px;">Missed Punch-Out Alert</div>
    </div>
    <div style="padding: 24px 20px;">
      <p style="margin-top: 0; font-size: 14px;">Dear HR,</p>
      <p style="font-size: 13px; color: #475569; line-height: 1.6;">
        <strong>{employee_name_esc}</strong> checked in but never checked out. Please review and correct their
        check-out time from the Attendance page.
      </p>
      <table style="width: 100%; border-collapse: collapse; font-size: 13px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; overflow: hidden;">
        <tr><td style="padding: 10px 14px; color: #64748b; border-bottom: 1px solid #e2e8f0;">Date</td><td style="padding: 10px 14px; text-align: right; font-weight: 700; border-bottom: 1px solid #e2e8f0;">{date_str_esc}</td></tr>
        <tr><td style="padding: 10px 14px; color: #64748b;">Check-In</td><td style="padding: 10px 14px; text-align: right; font-weight: 700;">{check_in_esc}</td></tr>
      </table>
      <p style="font-size: 12px; color: #94a3b8; margin-top: 20px;">Best regards,<br><strong>HR &amp; Administration Team</strong><br>{sender_name_esc}</p>
    </div>
  </div>
</body>
</html>"""
    return _send_email(to_email, subject, html_body)


def send_missed_checkout_reminder_email(
    to_email: str, employee_name: str, date_str: str, check_in: str, company_name: str = "",
) -> bool:
    """Remind the employee themselves that they forgot to punch out."""
    if not to_email or "@" not in to_email:
        logger.warning("Invalid employee email for missed-checkout reminder: %s", to_email)
        return False

    from html import escape
    sender_name = company_name or getattr(settings, "APP_NAME", "Pay Slip Pro")
    subject = f"Reminder: You didn't punch out on {date_str}"
    employee_name_esc, date_str_esc, check_in_esc, sender_name_esc = (
        escape(str(v)) for v in (employee_name, date_str, check_in or '-', sender_name)
    )

    html_body = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f8fafc; margin: 0; padding: 24px; color: #1e293b;">
  <div style="max-width: 460px; margin: 0 auto; background-color: #ffffff; border-radius: 16px; overflow: hidden; border: 1px solid #e2e8f0; box-shadow: 0 4px 14px rgba(0,0,0,0.06);">
    <div style="background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%); color: #ffffff; padding: 24px 20px; text-align: center;">
      <div style="font-size: 20px; font-weight: 800;">{sender_name_esc}</div>
      <div style="font-size: 13px; opacity: 0.95; margin-top: 4px;">Missed Punch-Out</div>
    </div>
    <div style="padding: 24px 20px;">
      <p style="margin-top: 0; font-size: 14px;">Dear <strong>{employee_name_esc}</strong>,</p>
      <p style="font-size: 13px; color: #475569; line-height: 1.6;">
        You checked in on <strong>{date_str_esc}</strong> at <strong>{check_in_esc}</strong> but we didn't see a
        check-out. HR has been notified and will correct your record - please reach out to them if the check-in
        itself looks wrong.
      </p>
      <p style="font-size: 12px; color: #94a3b8; margin-top: 20px;">Best regards,<br><strong>HR &amp; Administration Team</strong><br>{sender_name_esc}</p>
    </div>
  </div>
</body>
</html>"""
    return _send_email(to_email, subject, html_body)
