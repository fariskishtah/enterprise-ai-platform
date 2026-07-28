"""UUID-only queue boundary for transactional email delivery."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.observability.tracing import start_dramatiq_producer_span


class TransactionalEmailQueue(Protocol):
    def enqueue(self, message_id: UUID) -> str:
        """Publish one persisted message identifier and return the broker ID."""


class DramatiqTransactionalEmailQueue:
    def enqueue(self, message_id: UUID) -> str:
        from app.ml.jobs.tasks import deliver_transactional_email

        with start_dramatiq_producer_span("transactional_email"):
            message = deliver_transactional_email.send(str(message_id))
        return message.message_id
