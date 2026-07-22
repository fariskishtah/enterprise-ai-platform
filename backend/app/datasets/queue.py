"""UUID-only queue boundary for Dataset Registry processing."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID


class DatasetProcessingQueue(Protocol):
    def enqueue(self, version_id: UUID) -> str: ...


class DramatiqDatasetProcessingQueue:
    def enqueue(self, version_id: UUID) -> str:
        # Import lazily so API startup does not initialize the worker broker twice.
        from app.ml.jobs.tasks import process_dataset_version

        message = process_dataset_version.send(str(version_id))
        return message.message_id
