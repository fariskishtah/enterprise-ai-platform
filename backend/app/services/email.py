"""Provider-agnostic transactional email adapters and safe templates."""

from __future__ import annotations

import asyncio
import smtplib
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formataddr
from typing import Protocol
from uuid import uuid4
from xml.etree.ElementTree import Element, SubElement, tostring

import httpx

from app.config.settings import Settings
from app.models.email import EmailMessageType
from app.models.support import SupportRequest

RESEND_EMAIL_ENDPOINT = "https://api.resend.com/emails"


class EmailDeliveryError(RuntimeError):
    """Safe provider failure carrying only retry classification."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class OutboundEmail:
    to: str
    from_address: str
    from_name: str
    reply_to: str | None
    subject: str
    text: str
    html: str


@dataclass(frozen=True, slots=True)
class EmailDeliveryResult:
    provider_message_id: str
    captured: bool = False


class EmailProvider(Protocol):
    async def send(self, message: OutboundEmail) -> EmailDeliveryResult:
        """Deliver or explicitly capture one bounded transactional email."""


class DisabledEmailProvider:
    async def send(self, message: OutboundEmail) -> EmailDeliveryResult:
        del message
        raise EmailDeliveryError("Email delivery is not configured.")


@dataclass(slots=True)
class CaptureEmailProvider:
    """Development adapter that records messages without claiming delivery."""

    messages: list[OutboundEmail] = field(default_factory=list)

    async def send(self, message: OutboundEmail) -> EmailDeliveryResult:
        self.messages.append(message)
        return EmailDeliveryResult(
            provider_message_id=f"capture-{uuid4()}", captured=True
        )


class ResendEmailProvider:
    """Small Resend adapter with retry classification and no payload logging."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def send(self, message: OutboundEmail) -> EmailDeliveryResult:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    RESEND_EMAIL_ENDPOINT,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "from": formataddr((message.from_name, message.from_address)),
                        "to": [message.to],
                        "reply_to": message.reply_to,
                        "subject": message.subject,
                        "text": message.text,
                        "html": message.html,
                    },
                )
        except httpx.HTTPError as exc:
            raise EmailDeliveryError(
                "The email provider is temporarily unavailable.", retryable=True
            ) from exc
        if response.status_code == 429 or response.status_code >= 500:
            raise EmailDeliveryError(
                "The email provider is temporarily unavailable.", retryable=True
            )
        if response.status_code < 200 or response.status_code >= 300:
            raise EmailDeliveryError("The email provider rejected the request.")
        try:
            message_id = response.json().get("id")
        except ValueError as exc:
            raise EmailDeliveryError(
                "The email provider returned an invalid response."
            ) from exc
        if not isinstance(message_id, str) or not message_id or len(message_id) > 255:
            raise EmailDeliveryError("The email provider returned an invalid response.")
        return EmailDeliveryResult(provider_message_id=message_id)


class SMTPEmailProvider:
    """SMTP adapter whose blocking protocol exchange runs outside the event loop."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str | None,
        password: str | None,
        use_tls: bool,
        timeout_seconds: float,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._use_tls = use_tls
        self._timeout_seconds = timeout_seconds

    async def send(self, message: OutboundEmail) -> EmailDeliveryResult:
        try:
            return await asyncio.to_thread(self._send_sync, message)
        except smtplib.SMTPResponseException as exc:
            retryable = 400 <= exc.smtp_code < 500
            raise EmailDeliveryError(
                "The SMTP provider rejected the request.", retryable=retryable
            ) from exc
        except (OSError, smtplib.SMTPException) as exc:
            raise EmailDeliveryError(
                "The SMTP provider is temporarily unavailable.", retryable=True
            ) from exc

    def _send_sync(self, message: OutboundEmail) -> EmailDeliveryResult:
        email = EmailMessage()
        email["To"] = message.to
        email["From"] = formataddr((message.from_name, message.from_address))
        if message.reply_to:
            email["Reply-To"] = message.reply_to
        email["Subject"] = message.subject
        email.set_content(message.text)
        email.add_alternative(message.html, subtype="html")
        with smtplib.SMTP(
            self._host, self._port, timeout=self._timeout_seconds
        ) as client:
            client.ehlo()
            if self._use_tls:
                client.starttls()
                client.ehlo()
            if self._username is not None and self._password is not None:
                client.login(self._username, self._password)
            refused = client.send_message(email)
        if refused:
            raise EmailDeliveryError("The SMTP provider rejected a recipient.")
        return EmailDeliveryResult(provider_message_id=f"smtp-{uuid4()}")


def configured_email_provider(settings: Settings) -> EmailProvider:
    """Build the explicitly selected provider from validated settings."""
    if settings.email_provider == "capture":
        return CaptureEmailProvider()
    if settings.email_provider == "resend" and settings.resend_api_key is not None:
        return ResendEmailProvider(settings.resend_api_key.get_secret_value())
    if settings.email_provider == "smtp" and settings.smtp_host is not None:
        return SMTPEmailProvider(
            host=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_username,
            password=(
                settings.smtp_password.get_secret_value()
                if settings.smtp_password is not None
                else None
            ),
            use_tls=settings.smtp_use_tls,
            timeout_seconds=settings.smtp_timeout_seconds,
        )
    return DisabledEmailProvider()


_TEMPLATE_TITLES = {
    EmailMessageType.EMAIL_VERIFICATION: "Verify your email address",
    EmailMessageType.PASSWORD_RESET: "Reset your password",
    EmailMessageType.WELCOME: "Welcome to FK SOLUTIONS",
    EmailMessageType.TEAM_INVITATION: "You are invited to join your team",
    EmailMessageType.FEEDBACK_RECEIVED: "We received your feedback",
    EmailMessageType.SUPPORT_REQUEST_RECEIVED: "Support request received",
    EmailMessageType.SUBSCRIPTION_CONFIRMATION: "Subscription confirmed",
    EmailMessageType.PAYMENT_CONFIRMATION: "Payment confirmed",
    EmailMessageType.PAYMENT_FAILURE: "Payment needs your attention",
    EmailMessageType.SUBSCRIPTION_CANCELLATION: "Subscription cancellation",
}


def transactional_email(
    message_type: EmailMessageType,
    *,
    recipient: str,
    from_address: str,
    from_name: str,
    reply_to: str | None,
    intro: str,
    details: tuple[tuple[str, str], ...] = (),
    action_label: str | None = None,
    action_url: str | None = None,
) -> OutboundEmail:
    """Render one branded, escaped, responsive HTML email and text fallback."""
    title = _TEMPLATE_TITLES[message_type]
    text_lines = [title, "", intro]
    text_lines.extend(f"{label}: {value}" for label, value in details)
    if action_label and action_url:
        text_lines.extend(("", f"{action_label}: {action_url}"))
    text_lines.extend(("", "FK SOLUTIONS · AI Manufacturing Platform"))

    root = Element(
        "div",
        {
            "style": (
                "max-width:640px;margin:0 auto;padding:32px 20px;"
                "font-family:Arial,sans-serif;color:#172033;line-height:1.55"
            )
        },
    )
    brand = SubElement(
        root,
        "p",
        {"style": "font-weight:700;color:#155eef;letter-spacing:.04em"},
    )
    brand.text = "FK SOLUTIONS"
    heading = SubElement(root, "h1", {"style": "font-size:26px;margin:12px 0"})
    heading.text = title
    paragraph = SubElement(root, "p")
    paragraph.text = intro
    if details:
        table = SubElement(
            root, "table", {"style": "width:100%;border-collapse:collapse"}
        )
        for label, value in details:
            row = SubElement(table, "tr")
            key = SubElement(
                row,
                "th",
                {"style": "text-align:left;padding:6px 12px 6px 0"},
            )
            key.text = label
            cell = SubElement(row, "td", {"style": "padding:6px 0"})
            cell.text = value
    if action_label and action_url:
        action = SubElement(
            root,
            "a",
            {
                "href": action_url,
                "style": (
                    "display:inline-block;margin:20px 0;padding:12px 18px;"
                    "background:#155eef;color:#fff;text-decoration:none;border-radius:6px"
                ),
            },
        )
        action.text = action_label
    footer = SubElement(
        root,
        "p",
        {"style": "margin-top:28px;color:#667085;font-size:13px"},
    )
    footer.text = "FK SOLUTIONS · AI Manufacturing Platform"
    return OutboundEmail(
        to=recipient,
        from_address=from_address,
        from_name=from_name,
        reply_to=reply_to,
        subject=title,
        text="\n".join(text_lines),
        html=tostring(root, encoding="unicode", method="html"),
    )


def support_email(
    request: SupportRequest,
    *,
    destination: str,
    from_address: str,
    from_name: str = "FK SOLUTIONS",
    factory_name: str | None,
    machine_name: str | None,
) -> OutboundEmail:
    """Build the support-notification template from a persisted request."""
    details = (
        ("Support request ID", str(request.id)),
        ("User name", request.requester_name),
        ("User email", request.requester_email),
        ("Role", request.requester_role),
        ("Company", request.company_name),
        ("Category", request.category.replace("_", " ").title()),
        ("Subject", request.subject),
        ("Current page", request.current_page),
        ("Related factory", factory_name or "Not provided"),
        ("Related machine", machine_name or "Not provided"),
        ("Submitted timestamp", request.created_at.isoformat()),
        ("Message", request.message),
    )
    message = transactional_email(
        EmailMessageType.SUPPORT_REQUEST_RECEIVED,
        recipient=destination,
        from_address=from_address,
        from_name=from_name,
        reply_to=request.requester_email,
        intro="A customer submitted a support request from the platform.",
        details=details,
    )
    return OutboundEmail(
        to=message.to,
        from_address=message.from_address,
        from_name=message.from_name,
        reply_to=message.reply_to,
        subject=f"[FK Support] {request.subject}",
        text=message.text,
        html=message.html,
    )
