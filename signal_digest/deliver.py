"""Email delivery via Resend API."""

import logging
import os
from datetime import datetime, timezone

import resend

logger = logging.getLogger(__name__)

FROM_ADDRESS = "Signal Digest <onboarding@resend.dev>"


def send_digest(body: str, config: dict, test_mode: bool = False) -> None:
    """Send the digest email via Resend."""
    _init_resend()
    recipient = _get_recipient()

    today = datetime.now(timezone.utc).strftime("%b %d, %Y")
    subject = config["subject_template"].format(date=today)
    if test_mode:
        subject = f"[TEST] {subject}"

    # Append footer
    full_body = f"{body}\n\n---\nSignal Digest — {config['name']}\nGenerated {today}"

    logger.info(f"Sending digest email: {subject}")

    try:
        params = {
            "from_": FROM_ADDRESS,
            "to": [recipient],
            "subject": subject,
            "text": full_body,
        }
        resend.Emails.send(params)
        logger.info("Digest email sent successfully")
    except Exception as e:
        logger.error(f"Failed to send digest email: {e}")
        raise


def send_error_notification(config_name: str, error: str) -> None:
    """Send a failure notification email."""
    try:
        _init_resend()
        recipient = _get_recipient()
    except RuntimeError as e:
        logger.error(f"Cannot send error notification: {e}")
        return

    today = datetime.now(timezone.utc).strftime("%b %d, %Y")
    now = datetime.now(timezone.utc).isoformat()

    subject = f"Signal: {config_name} — run failed {today}"
    body = (
        f"The digest run for '{config_name}' failed.\n\n"
        f"Error:\n{error}\n\n"
        f"Timestamp: {now}\n\n"
        f"Check GitHub Actions logs for full details."
    )

    try:
        params = {
            "from_": FROM_ADDRESS,
            "to": [recipient],
            "subject": subject,
            "text": body,
        }
        resend.Emails.send(params)
        logger.info("Error notification email sent")
    except Exception as e:
        logger.error(f"Failed to send error notification: {e}")


def _init_resend() -> None:
    """Initialize Resend API key from environment."""
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        raise RuntimeError("RESEND_API_KEY environment variable not set")
    resend.api_key = api_key


def _get_recipient() -> str:
    """Get recipient email from environment."""
    recipient = os.environ.get("RECIPIENT_EMAIL")
    if not recipient:
        raise RuntimeError("RECIPIENT_EMAIL environment variable not set")
    return recipient
