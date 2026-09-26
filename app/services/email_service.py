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
