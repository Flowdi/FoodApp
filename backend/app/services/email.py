import logging
import smtplib
from email.message import EmailMessage

from ..config import get_settings

logger = logging.getLogger(__name__)


def send_email(recipient: str, subject: str, body: str) -> bool:
    settings = get_settings()
    if not settings.smtp_host:
        return False
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.smtp_from
    message["To"] = recipient
    message.set_content(body)
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
            smtp.starttls()
            if settings.smtp_username:
                smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(message)
        return True
    except (OSError, smtplib.SMTPException):
        logger.exception("Could not send email to %s", recipient)
        return False
