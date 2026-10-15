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

    # Format duration
    if request_type.upper() == 'PERMISSION':
        duration_str = f"{duration_hours or 2} Hours"
    elif request_type.upper() == 'HALF_DAY':
        duration_str = "Half Day (0.5 Day)"
    else:
        try:
            from datetime import datetime
            d1 = datetime.strptime(start_date, '%Y-%m-%d')
            d2 = datetime.strptime(end_date, '%Y-%m-%d')
            days_count = max(1, (d2 - d1).days + 1)
            duration_str = f"{days_count} Day{'s' if days_count > 1 else ''}"
        except Exception:
            duration_str = "1 Day"

    from html import escape
    approve_url = escape(f"{settings.FRONTEND_URL.rstrip('/')}/attendance?leave_request={request_id}", quote=True)
    reject_url = approve_url
    employee_name, employee_email, reason, sender_name = (escape(str(value)) for value in (employee_name, employee_email, reason, sender_name))
    type_label, start_date, end_date = (escape(str(value)) for value in (type_label, start_date, end_date))

    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #121212; margin: 0; padding: 24px 12px; color: #f1f5f9; }}
        .card {{ max-width: 440px; margin: 0 auto; background-color: #18181b; border-radius: 20px; overflow: hidden; border: 1px solid #27272a; box-shadow: 0 12px 36px rgba(0,0,0,0.6); }}
        .header {{ background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%); color: #ffffff; padding: 26px 20px; text-align: center; }}
        .header h2 {{ margin: 0; font-size: 21px; font-weight: 800; }}
        .header p {{ margin: 4px 0 0 0; font-size: 13px; opacity: 0.95; }}
        .body {{ padding: 24px 20px; }}
        .greeting {{ font-size: 15px; font-weight: 800; margin-bottom: 4px; color: #ffffff; }}
        .subtext {{ font-size: 13px; color: #a1a1aa; margin-bottom: 18px; }}
        .table-box {{ width: 100%; border-collapse: collapse; border-radius: 12px; overflow: hidden; background: #27272a; border: 1px solid #3f3f46; margin-bottom: 24px; font-size: 13px; }}
        .table-box tr {{ border-bottom: 1px solid #3f3f46; }}
        .table-box tr:last-child {{ border-bottom: none; }}
        .table-box td {{ padding: 12px 14px; }}
        .table-box td.label {{ width: 38%; color: #94a3b8; font-weight: 700; background: #202023; white-space: nowrap; }}
        .table-box td.val {{ color: #ffffff; font-weight: 600; word-break: break-word; }}
        .actions-title {{ text-align: center; font-size: 13px; font-weight: 800; color: #e4e4e7; margin-bottom: 12px; }}
        .btn-container {{ text-align: center; margin-bottom: 12px; display: flex; flex-direction: column; gap: 10px; align-items: center; }}
        .btn-approve {{ display: block; width: 90%; max-width: 280px; padding: 12px 0; background: #10b981; color: #ffffff !important; text-decoration: none; border-radius: 10px; font-weight: 800; font-size: 14px; box-shadow: 0 4px 14px rgba(16, 185, 129, 0.4); text-align: center; margin: 0 auto 10px auto; }}
        .btn-reject {{ display: block; width: 90%; max-width: 280px; padding: 12px 0; background: #ef4444; color: #ffffff !important; text-decoration: none; border-radius: 10px; font-weight: 800; font-size: 14px; box-shadow: 0 4px 14px rgba(239, 68, 68, 0.4); text-align: center; margin: 0 auto; }}
        .footer {{ background: #18181b; border-top: 1px solid #27272a; padding: 14px; text-align: center; font-size: 11px; color: #71717a; }}
      </style>
    </head>
    <body>
      <div class="card">
        <div class="header">
          <h2>📋 New Leave Request</h2>
          <p>{sender_name}</p>
        </div>
        <div class="body">
          <div class="greeting">Dear MD,</div>
          <div class="subtext">A new leave request needs your approval:</div>

          <table class="table-box">
            <tr>
              <td class="label">👤 Employee</td>
              <td class="val">{employee_name}</td>
            </tr>
            <tr>
              <td class="label">📧 Email</td>
              <td class="val">{employee_email}</td>
            </tr>
            <tr>
              <td class="label">📝 Type</td>
              <td class="val">{type_label}</td>
            </tr>
            <tr>
              <td class="label">📅 From</td>
              <td class="val">{start_date}</td>
            </tr>
            <tr>
              <td class="label">📅 To</td>
              <td class="val">{end_date}</td>
            </tr>
            <tr>
              <td class="label">⏱️ Days/Hours</td>
              <td class="val">{duration_str}</td>
            </tr>
            <tr>
              <td class="label">💬 Reason</td>
              <td class="val">{reason}</td>
            </tr>
          </table>

          <div class="actions-title">Take Action:</div>
          <div class="btn-container">
            <a href="{approve_url}" class="btn-approve" target="_blank">✅ APPROVE</a>
            <a href="{reject_url}" class="btn-reject" target="_blank">❌ REJECT</a>
          </div>
        </div>
        <div class="footer">
          {sender_name} - HR System
        </div>
      </div>
    </body>
    </html>
    """
    return _send_email(to_email, subject, html_body)
