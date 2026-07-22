"""Dataset Registry dependency composition."""

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings, get_settings
from app.datasets.queue import (
    DatasetProcessingQueue,
    DramatiqDatasetProcessingQueue,
)
from app.datasets.service import DatasetLimits, DatasetService
from app.datasets.storage import LocalDatasetObjectStorage
from app.dependencies.database import get_db_session
from app.repositories.datasets import DatasetRepository


@lru_cache
def get_dataset_storage(root: str) -> LocalDatasetObjectStorage:
    return LocalDatasetObjectStorage(Path(root))


def get_dataset_queue() -> DatasetProcessingQueue:
    return DramatiqDatasetProcessingQueue()


def get_dataset_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    queue: Annotated[DatasetProcessingQueue, Depends(get_dataset_queue)],
) -> DatasetService:
    return DatasetService(
        repository=DatasetRepository(session),
        storage=get_dataset_storage(settings.dataset_storage_root),
        queue=queue,
        limits=DatasetLimits(
            upload_bytes=settings.dataset_upload_max_bytes,
            maximum_rows=settings.dataset_max_rows,
            maximum_columns=settings.dataset_max_columns,
            maximum_cell_characters=settings.dataset_max_cell_characters,
            maximum_document_characters=settings.dataset_max_document_characters,
            stale_after_seconds=settings.dataset_processing_stale_after_seconds,
            maximum_enqueue_attempts=(settings.dataset_processing_max_enqueue_attempts),
        ),
    )
