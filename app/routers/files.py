from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.logging_config import get_logger
from app.models import AuditEvent, FileRecord, User
from app.dependencies import get_current_user
from app.schemas import (
    AuditEventOut,
    FileMetadata,
    SignedLinkResponse,
    SignRequest,
)
from app.security import generate_stored_name, sign_file_access
from app.storage import delete_stored_file, save_upload

router = APIRouter(prefix="/files", tags=["files"])
log = get_logger("app.files")

MAX_FILENAME_LENGTH = 255


def _clean_filename(name: str | None) -> str:
    if not name or not name.strip():
        return "unnamed"
    # keep only the base name — discard any path components the client sent
    base = name.replace("\\", "/").split("/")[-1].strip()
    return (base or "unnamed")[:MAX_FILENAME_LENGTH]


@router.post("", response_model=FileMetadata, status_code=status.HTTP_201_CREATED)
def upload_file(
    file: UploadFile,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stored_name = generate_stored_name()
    size = save_upload(file, stored_name)

    if size == 0:
        delete_stored_file(stored_name)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty",
        )

    record = FileRecord(
        owner_id=current_user.id,
        original_filename=_clean_filename(file.filename),
        stored_name=stored_name,
        content_type=file.content_type or "application/octet-stream",
        size_bytes=size,
    )

    try:
        db.add(record)
        db.commit()
        db.refresh(record)
    except Exception:
        db.rollback()
        delete_stored_file(stored_name)
        raise

    db.add(
        AuditEvent(
            event_type="file_uploaded",
            file_id=record.id,
            user_id=current_user.id,
            detail=record.original_filename,
        )
    )
    db.commit()

    log.info(
        "file_uploaded",
        file_id=record.id,
        user_id=current_user.id,
        size_bytes=size,
    )
    return record


@router.get("", response_model=list[FileMetadata])
def list_files(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    records = (
        db.query(FileRecord)
        .filter(FileRecord.owner_id == current_user.id)
        .order_by(FileRecord.created_at.desc())
        .all()
    )
    return records


def _owned_file_or_404(db: Session, file_id: int, user: User) -> FileRecord:
    record = db.get(FileRecord, file_id)
    if record is None or record.owner_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="File not found"
        )
    return record


@router.get("/{file_id}", response_model=FileMetadata)
def get_file_metadata(
    file_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _owned_file_or_404(db, file_id, current_user)


@router.post("/{file_id}/sign", response_model=SignedLinkResponse)
def create_signed_link(
    file_id: int,
    payload: SignRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    record = _owned_file_or_404(db, file_id, current_user)

    expires_at, signature = sign_file_access(record.id, payload.ttl_seconds)
    expires_dt = datetime.fromtimestamp(expires_at, tz=timezone.utc)

    db.add(
        AuditEvent(
            event_type="link_generated",
            file_id=record.id,
            user_id=current_user.id,
            ttl_seconds=payload.ttl_seconds,
            expires_at=expires_dt,
        )
    )
    db.commit()

    download_url = str(
        request.url_for("download_file").include_query_params(
            file_id=record.id, expires=expires_at, signature=signature
        )
    )

    log.info(
        "link_generated",
        file_id=record.id,
        user_id=current_user.id,
        ttl_seconds=payload.ttl_seconds,
        expires_at=expires_dt.isoformat(),
    )

    return SignedLinkResponse(
        file_id=record.id,
        expires_at=expires_dt,
        ttl_seconds=payload.ttl_seconds,
        download_url=download_url,
    )


@router.get("/{file_id}/audit", response_model=list[AuditEventOut])
def file_audit_trail(
    file_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    record = _owned_file_or_404(db, file_id, current_user)
    events = (
        db.query(AuditEvent)
        .filter(AuditEvent.file_id == record.id)
        .order_by(AuditEvent.created_at.desc())
        .all()
    )
    return events