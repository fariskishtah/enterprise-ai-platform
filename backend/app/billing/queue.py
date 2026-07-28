"""UUID-only billing webhook queue boundary."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.observability.tracing import start_dramatiq_producer_span


class BillingWebhookQueue(Protocol):
    def enqueue(self, event_id: UUID) -> str:
        """Publish one persisted webhook identifier."""


class DramatiqBillingWebhookQueue:
    def enqueue(self, event_id: UUID) -> str:
        from app.ml.jobs.tasks import process_billing_webhook

        with start_dramatiq_producer_span("billing_webhook"):
            message = process_billing_webhook.send(str(event_id))
        return message.message_id
