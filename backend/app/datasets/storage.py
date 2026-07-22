"""Generated-key, root-confined byte storage for registered datasets."""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol
from uuid import uuid4


class DatasetStorageError(RuntimeError):
    """Raised when bounded object storage cannot safely complete an operation."""


@dataclass(frozen=True, slots=True)
class StoredObject:
    key: str
    size_bytes: int
    sha256_digest: str


class DatasetObjectStorage(Protocol):
    def write(self, source: BinaryIO, *, maximum_bytes: int) -> StoredObject: ...
    def read(self, key: str, *, maximum_bytes: int) -> bytes: ...
    def delete(self, key: str) -> None: ...
    def stat(self, key: str, *, maximum_bytes: int) -> StoredObject: ...
    def verify(self, key: str, digest: str, *, maximum_bytes: int) -> bool: ...


class LocalDatasetObjectStorage:
    """Persist opaque objects below an application-controlled directory."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def write(self, source: BinaryIO, *, maximum_bytes: int) -> StoredObject:
        if maximum_bytes <= 0:
            raise ValueError("Maximum object size must be positive.")
        key = f"{uuid4().hex[:2]}/{uuid4().hex}"
        destination = self._path(key)
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        digest = hashlib.sha256()
        size = 0
        source.seek(0)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=destination.parent, prefix=".upload-", delete=False
            ) as temporary:
                temporary_path = Path(temporary.name)
                while chunk := source.read(64 * 1024):
                    size += len(chunk)
                    if size > maximum_bytes:
                        raise DatasetStorageError("The uploaded object is too large.")
                    digest.update(chunk)
                    temporary.write(chunk)
                if size == 0:
                    raise DatasetStorageError("The uploaded object is empty.")
                temporary.flush()
                os.fsync(temporary.fileno())
            if destination.exists() or destination.is_symlink():
                raise DatasetStorageError("The generated object key already exists.")
            os.replace(temporary_path, destination)
            temporary_path = None
            return StoredObject(key, size, digest.hexdigest())
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def read(self, key: str, *, maximum_bytes: int) -> bytes:
        path = self._path(key)
        if not path.is_file() or path.is_symlink():
            raise DatasetStorageError("The stored object is unavailable.")
        size = path.stat().st_size
        if size <= 0 or size > maximum_bytes:
            raise DatasetStorageError("The stored object size is invalid.")
        return path.read_bytes()

    def delete(self, key: str) -> None:
        path = self._path(key)
        if path.is_symlink():
            raise DatasetStorageError("Symbolic links are not valid storage objects.")
        path.unlink(missing_ok=True)

    def stat(self, key: str, *, maximum_bytes: int) -> StoredObject:
        if maximum_bytes <= 0:
            raise ValueError("Maximum object size must be positive.")
        path = self._path(key)
        if not path.is_file() or path.is_symlink():
            raise DatasetStorageError("The stored object is unavailable.")
        expected_size = path.stat().st_size
        if expected_size <= 0 or expected_size > maximum_bytes:
            raise DatasetStorageError("The stored object size is invalid.")
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as source:
            while chunk := source.read(64 * 1024):
                size += len(chunk)
                if size > maximum_bytes:
                    raise DatasetStorageError("The stored object size is invalid.")
                digest.update(chunk)
        if size != expected_size:
            raise DatasetStorageError("The stored object changed during verification.")
        return StoredObject(key, size, digest.hexdigest())

    def verify(self, key: str, digest: str, *, maximum_bytes: int) -> bool:
        return self.stat(key, maximum_bytes=maximum_bytes).sha256_digest == digest

    def _path(self, key: str) -> Path:
        parts = key.split("/")
        if (
            len(parts) != 2
            or len(parts[0]) != 2
            or len(parts[1]) != 32
            or any(not part.isalnum() for part in parts)
        ):
            raise DatasetStorageError("The storage key is invalid.")
        candidate = self._root.joinpath(*parts).resolve()
        try:
            candidate.relative_to(self._root)
        except ValueError as exc:
            raise DatasetStorageError("The storage key escaped its root.") from exc
        return candidate
