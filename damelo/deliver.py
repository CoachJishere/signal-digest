"""Email delivery via Resend API."""

import logging
import os
import re
from datetime import datetime, timezone

import resend

logger = logging.getLogger(__name__)

FROM_ADDRESS = "Damelo <onboarding@resend.dev>"


def send_digest(body: str, config: dict, test_mode: bool = False) -> None:
    """Send the digest email via Resend."""
    _init_resend()
    recipient = _get_recipient()

    today = datetime.now(timezone.utc).strftime("%b %d, %Y")
    subject = config["subject_template"].format(date=today)
    if test_mode:
        subject = f"[TEST] {subject}"

    # Append footer
    full_body = f"{body}\n\n---\nDamelo — {config['name']}\nGenerated {today}"

    # Convert markdown to simple HTML for email rendering
    html_body = _markdown_to_html(full_body)

    logger.info(f"Sending digest email: {subject}")

    try:
        resend.Emails.send({
            "from": FROM_ADDRESS,
            "to": [recipient],
            "subject": subject,
            "html": html_body,
        })
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
        resend.Emails.send({
            "from": FROM_ADDRESS,
            "to": [recipient],
            "subject": subject,
            "text": body,
        })
        logger.info("Error notification email sent")
    except Exception as e:
        logger.error(f"Failed to send error notification: {e}")


def _markdown_to_html(text: str) -> str:
    """Convert markdown-formatted text to simple HTML for email.

    Handles: headers, bold, italic, links, horizontal rules, paragraphs.
    No external dependency needed.
    """
    lines = text.split("\n")
    html_lines = []
    in_paragraph = False

    for line in lines:
        stripped = line.strip()

        # Horizontal rule
        if stripped in ("---", "***", "___"):
            if in_paragraph:
                html_lines.append("</p>")
                in_paragraph = False
            html_lines.append("<hr>")
            continue

        # Headers
        header_match = re.match(r"^(#{1,3})\s+(.+)$", stripped)
        if header_match:
            if in_paragraph:
                html_lines.append("</p>")
                in_paragraph = False
            level = len(header_match.group(1))
            content = _inline_markdown(header_match.group(2))
            html_lines.append(f"<h{level}>{content}</h{level}>")
            continue

        # Empty line — close paragraph
        if not stripped:
            if in_paragraph:
                html_lines.append("</p>")
                in_paragraph = False
            continue

        # Regular text — open paragraph if needed
        if not in_paragraph:
            html_lines.append("<p>")
            in_paragraph = True
        else:
            html_lines.append("<br>")

        html_lines.append(_inline_markdown(stripped))

    if in_paragraph:
        html_lines.append("</p>")

    body = "\n".join(html_lines)

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; color: #1a1a1a; font-size: 15px; line-height: 1.6;">
{body}
</body>
</html>"""


def _inline_markdown(text: str) -> str:
    """Convert inline markdown: bold, italic, links."""
    # Links: [text](url)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2" style="color: #2563eb;">\1</a>', text)
    # Bold: **text**
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    # Italic: *text*
    text = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", text)
    return text


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
