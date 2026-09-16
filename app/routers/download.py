from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.logging_config import get_logger
from app.models import AuditEvent, FileRecord
from app.security import is_expired, verify_signature
from app.storage import resolve_stored_path, stored_file_exists

router = APIRouter(tags=["download"])
log = get_logger("app.download")


@router.get("/download", name="download_file")
def download_file(
    file_id: int = Query(..., ge=1),
    expires: int = Query(..., ge=0),
    signature: str = Query(..., min_length=64, max_length=64),
    db: Session = Depends(get_db),
):
    if not verify_signature(file_id, expires, signature):
        log.warning("signature_rejected", file_id=file_id)
        db.add(
            AuditEvent(
                event_type="signature_rejected",
                file_id=None,
                detail=f"invalid signature for file_id={file_id}",
            )
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid download signature",
        )

    if is_expired(expires):
        log.warning("link_expired", file_id=file_id)
        db.add(
            AuditEvent(
                event_type="link_expired",
                file_id=file_id,
                detail="download attempted after expiry",
            )
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Download link has expired",
        )

    record = db.get(FileRecord, file_id)
    if record is None or not stored_file_exists(record.stored_name):
        log.error("stored_file_missing", file_id=file_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="File not found"
        )

    db.add(
        AuditEvent(
            event_type="link_redeemed",
            file_id=record.id,
            user_id=record.owner_id,
        )
    )
    db.commit()

    log.info("link_redeemed", file_id=record.id)

    return FileResponse(
        path=resolve_stored_path(record.stored_name),
        media_type=record.content_type,
        filename=record.original_filename,
    )