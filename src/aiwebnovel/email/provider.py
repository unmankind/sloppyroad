"""Email sending via Resend.com for verification and notifications.

When ``resend_api_key`` is empty (dev mode), emails are logged to console
instead of being sent.
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)


async def send_verification_email(
    email: str,
    token: str,
    base_url: str,
    *,
    resend_api_key: str = "",
    sender: str = "noreply@sloppyroad.com",
) -> bool:
    """Send an email-verification link to the given address.

    Returns ``True`` if the email was sent (or logged in dev mode).
    """
    verification_url = f"{base_url}/auth/verify-email/{token}"

    subject = "Verify your SloppyRoad account"
    html_body = _build_verification_html(verification_url)

    if not resend_api_key:
        # Dev mode — just log it
        logger.info(
            "email_verification_dev",
            to=email,
            verification_url=verification_url,
        )
        return True

    try:
        import resend

        resend.api_key = resend_api_key
        resend.Emails.send(
            {
                "from": f"SloppyRoad <{sender}>",
                "to": [email],
                "subject": subject,
                "html": html_body,
            }
        )
        logger.info("email_verification_sent", to=email)
        return True
    except Exception:
        logger.exception("email_verification_failed", to=email)
        return False


def _build_verification_html(verification_url: str) -> str:
    """Build a SloppyRoad-branded verification email."""
    return f"""\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="
  font-family: Georgia, 'Times New Roman', serif;
  background: #0a0a0f;
  color: #e8e0d4;
  padding: 40px 20px;
  margin: 0;
">
  <div style="
    max-width: 480px;
    margin: 0 auto;
    background: #13131a;
    border: 1px solid #2a2a3a;
    border-radius: 8px;
    padding: 40px;
  ">
    <h1 style="
      font-size: 24px;
      color: #a78bfa;
      margin: 0 0 8px 0;
    ">SloppyRoad</h1>
    <p style="
      color: #8a8090;
      font-size: 13px;
      margin: 0 0 32px 0;
      font-style: italic;
    ">Certified AI Slop</p>

    <p style="font-size: 16px; line-height: 1.6;">
      Welcome, aspiring slop merchant. Click the button below to verify
      your account and start generating questionable literature.
    </p>

    <div style="text-align: center; margin: 32px 0;">
      <a href="{verification_url}" style="
        display: inline-block;
        background: #7c3aed;
        color: #ffffff;
        padding: 14px 32px;
        border-radius: 6px;
        text-decoration: none;
        font-size: 16px;
        font-weight: bold;
      ">Verify My Account</a>
    </div>

    <p style="font-size: 13px; color: #8a8090; line-height: 1.5;">
      If the button doesn't work, copy this link:<br>
      <a href="{verification_url}" style="color: #a78bfa; word-break: break-all;">
        {verification_url}
      </a>
    </p>

    <p style="
      font-size: 12px;
      color: #5a5060;
      margin-top: 32px;
      border-top: 1px solid #2a2a3a;
      padding-top: 16px;
    ">
      This link expires in 24 hours. If you didn't create a SloppyRoad
      account, you can safely ignore this email.
    </p>
  </div>
</body>
</html>"""
