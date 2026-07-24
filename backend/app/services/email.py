"""Narrow outbound email boundary for authenticated support requests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from xml.etree.ElementTree import Element, SubElement, tostring

import httpx

from app.config.settings import Settings
from app.models.support import SupportRequest

RESEND_EMAIL_ENDPOINT = "https://api.resend.com/emails"


class EmailDeliveryError(RuntimeError):
    """Safe delivery failure without provider response or credential details."""


@dataclass(frozen=True)
class OutboundEmail:
    to: str
    from_address: str
    reply_to: str
    subject: str
    text: str
    html: str


@dataclass(frozen=True)
class EmailDeliveryResult:
    provider_message_id: str


class EmailProvider(Protocol):
    async def send(self, message: OutboundEmail) -> EmailDeliveryResult:
        """Deliver one bounded transactional email."""


class DisabledEmailProvider:
    async def send(self, message: OutboundEmail) -> EmailDeliveryResult:
        del message
        raise EmailDeliveryError("Email delivery is not configured.")


class ResendEmailProvider:
    """Small Resend adapter with no provider payload logging."""

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
                        "from": message.from_address,
                        "to": [message.to],
                        "reply_to": message.reply_to,
                        "subject": message.subject,
                        "text": message.text,
                        "html": message.html,
                    },
                )
        except httpx.HTTPError as exc:
            raise EmailDeliveryError(
                "The email provider is temporarily unavailable."
            ) from exc
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


def configured_email_provider(settings: Settings) -> EmailProvider:
    if settings.email_provider != "resend" or settings.resend_api_key is None:
        return DisabledEmailProvider()
    return ResendEmailProvider(settings.resend_api_key.get_secret_value())


def support_email(
    request: SupportRequest,
    *,
    destination: str,
    from_address: str,
    factory_name: str | None,
    machine_name: str | None,
) -> OutboundEmail:
    """Build escaped HTML and plain text from a persisted bounded request."""
    fields = [
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
        ("Delivery status at dispatch", request.status),
    ]
    text = "\n".join(f"{label}: {value}" for label, value in fields)
    text += f"\n\nMessage:\n{request.message}"
    root = Element("div")
    heading = SubElement(root, "h1")
    heading.text = "FK SOLUTIONS support request"
    table = SubElement(root, "table")
    for label, value in fields:
        row = SubElement(table, "tr")
        key = SubElement(
            row,
            "th",
            {"style": "text-align:left;padding:6px 12px 6px 0"},
        )
        key.text = label
        cell = SubElement(row, "td")
        cell.text = value
    message_heading = SubElement(root, "h2")
    message_heading.text = "Message"
    message = SubElement(root, "p", {"style": "white-space:pre-wrap"})
    message.text = request.message
    body = tostring(root, encoding="unicode", method="html")
    return OutboundEmail(
        to=destination,
        from_address=from_address,
        reply_to=request.requester_email,
        subject=f"[FK Support] {request.subject}",
        text=text,
        html=body,
    )
