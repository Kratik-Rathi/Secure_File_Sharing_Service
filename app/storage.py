import os
import shutil
from pathlib import Path

from fastapi import UploadFile

from app.config import settings

CHUNK_SIZE = 1024 * 1024  # 1 MiB


def storage_root() -> Path:
    root = Path(settings.storage_path).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def resolve_stored_path(stored_name: str) -> Path:
    """Resolve a stored filename to an absolute path inside the storage root.

    Raises ValueError if the result would escape the root.
    """
    root = storage_root()
    candidate = (root / stored_name).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("resolved path escapes storage root")
    return candidate


def save_upload(upload: UploadFile, stored_name: str) -> int:
    """Stream an upload to disk. Returns bytes written."""
    destination = resolve_stored_path(stored_name)
    written = 0
    try:
        with destination.open("wb") as out:
            while chunk := upload.file.read(CHUNK_SIZE):
                out.write(chunk)
                written += len(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return written


def delete_stored_file(stored_name: str) -> None:
    try:
        resolve_stored_path(stored_name).unlink(missing_ok=True)
    except ValueError:
        pass


def stored_file_exists(stored_name: str) -> bool:
    try:
        return resolve_stored_path(stored_name).is_file()
    except ValueError:
        return False
    