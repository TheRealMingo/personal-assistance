import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from langchain.tools import tool
import logging
from config.config import config

logging.basicConfig(filename='email_tool.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

SMTP_HOST = 'smtp.gmail.com'
SMTP_PORT = 587


def _get_smtp_credentials() -> tuple[str, str] | None:
    """Return (email, app_password) from config, or None if not configured."""
    email = config.get("gmail_smtp_email")
    password = config.get("gmail_smtp_app_password")
    if email and password:
        return email, password
    return None


def _send_via_smtp(message: MIMEMultipart) -> None:
    """Connect to Gmail SMTP, authenticate, and send the message."""
    creds = _get_smtp_credentials()
    if not creds:
        raise ValueError(
            "Gmail SMTP credentials are not configured. "
            "Set 'gmail_smtp_email' and 'gmail_smtp_app_password' in config/config.py."
        )
    email, password = creds
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(email, password)
        server.send_message(message)


@tool
def send_email_tool(
    recipient: str,
    subject: str,
    body: str,
    html: bool = False
) -> str:
    """
    Send an email using Gmail SMTP.

    Args:
        recipient: Email address of the recipient (or comma-separated list for multiple)
        subject: Subject line of the email
        body: Body of the email (plain text or HTML)
        html: Whether the body is HTML formatted (default: False for plain text)

    Returns:
        Confirmation message with email send status
    """
    try:
        creds = _get_smtp_credentials()
        if not creds:
            return (
                "❌ Failed to send email: SMTP credentials are not configured. "
                "Set 'gmail_smtp_email' and 'gmail_smtp_app_password' in config/config.py."
            )
        sender = creds[0]

        message = MIMEMultipart('alternative')
        message['To'] = recipient
        message['From'] = sender
        message['Subject'] = subject

        if html:
            message.attach(MIMEText(body, 'html'))
        else:
            message.attach(MIMEText(body, 'plain'))

        _send_via_smtp(message)

        logging.info(f"Email sent successfully to {recipient}")
        return f"✓ Email sent successfully to {recipient}\nSubject: {subject}"

    except Exception as e:
        error_msg = f"❌ Failed to send email: {str(e)}"
        logging.error(error_msg)
        return error_msg


@tool
def send_email_with_attachment_tool(
    recipient: str,
    subject: str,
    body: str,
    attachment_path: str = None,
    html: bool = False
) -> str:
    """
    Send an email with an optional attachment using Gmail SMTP.

    Args:
        recipient: Email address of the recipient
        subject: Subject line of the email
        body: Body of the email
        attachment_path: Path to file to attach (optional)
        html: Whether the body is HTML formatted

    Returns:
        Confirmation message with email send status
    """
    try:
        import os
        from email.mime.base import MIMEBase
        from email import encoders

        creds = _get_smtp_credentials()
        if not creds:
            return (
                "❌ Failed to send email: SMTP credentials are not configured. "
                "Set 'gmail_smtp_email' and 'gmail_smtp_app_password' in config/config.py."
            )
        sender = creds[0]

        message = MIMEMultipart()
        message['To'] = recipient
        message['From'] = sender
        message['Subject'] = subject

        if html:
            message.attach(MIMEText(body, 'html'))
        else:
            message.attach(MIMEText(body, 'plain'))

        if attachment_path and os.path.exists(attachment_path):
            with open(attachment_path, 'rb') as f:
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header(
                'Content-Disposition',
                f'attachment; filename={os.path.basename(attachment_path)}'
            )
            message.attach(part)
            logging.info(f"Attachment added: {attachment_path}")

        _send_via_smtp(message)

        logging.info(f"Email with attachment sent successfully to {recipient}")
        return f"✓ Email sent successfully to {recipient}\nSubject: {subject}"

    except Exception as e:
        error_msg = f"❌ Failed to send email: {str(e)}"
        logging.error(error_msg)
        return error_msg
