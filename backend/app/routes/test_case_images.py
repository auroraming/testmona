"""Controlled image attachments for test cases and structured steps."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import uuid

from fastapi import Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models, rbac, schemas
from ..auth import get_current_active_user
from ..database import get_db


MAX_IMAGE_BYTES = 5 * 1024 * 1024
IMAGE_TYPES = {
    "image/png": (".png", lambda data: data.startswith(b"\x89PNG\r\n\x1a\n")),
    "image/jpeg": (".jpg", lambda data: data.startswith(b"\xff\xd8\xff")),
    "image/gif": (".gif", lambda data: data.startswith((b"GIF87a", b"GIF89a"))),
    "image/webp": (".webp", lambda data: len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"),
}


def _storage_root() -> Path:
    return Path(os.getenv("TEST_CASE_IMAGE_DIR", "uploads/test-case-images")).resolve()


def _case_or_404(db: Session, test_case_id: int) -> models.TestCase:
    test_case = db.query(models.TestCase).filter(
        models.TestCase.id == test_case_id,
        models.TestCase.is_deleted.is_(False),
    ).first()
    if test_case is None:
        raise HTTPException(status_code=404, detail="Test case not found")
    return test_case


def _require(db: Session, user: models.User, test_case: models.TestCase, permission: str) -> None:
    project_id = test_case.project_id or test_case.test_suite.project_id
    if not rbac.has_permission(user, permission, project_id, db):
        raise HTTPException(status_code=403, detail="Insufficient permissions")


def _image_path(test_case: models.TestCase, storage_key: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{32}\.(png|jpg|gif|webp)", storage_key):
        raise HTTPException(status_code=404, detail="Test case image file is unavailable")
    project_id = test_case.project_id or test_case.test_suite.project_id
    return _storage_root() / str(project_id) / str(test_case.id) / storage_key


def _view(image: models.TestCaseImage) -> dict:
    return {
        "id": image.id,
        "test_case_id": image.test_case_id,
        "test_step_id": image.test_step_id,
        "filename": image.filename,
        "mime_type": image.mime_type,
        "file_size": image.file_size,
        "sha256": image.sha256,
        "alt_text": image.alt_text,
        "uploaded_by": image.uploaded_by,
        "created_at": image.created_at,
        "updated_at": image.updated_at,
        "content_url": f"/test-cases/{image.test_case_id}/images/{image.id}/content",
    }


async def _write_image(file: UploadFile, destination: Path) -> tuple[int, str, str]:
    mime_type = (file.content_type or "").lower()
    config = IMAGE_TYPES.get(mime_type)
    if config is None:
        raise HTTPException(status_code=415, detail="Only PNG, JPEG, GIF, and WebP images are supported")
    destination.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    digest = hashlib.sha256()
    prefix = b""
    try:
        with destination.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_IMAGE_BYTES:
                    raise HTTPException(status_code=413, detail="Test case images are limited to 5 MB")
                if len(prefix) < 16:
                    prefix += chunk[:16 - len(prefix)]
                digest.update(chunk)
                output.write(chunk)
        if size == 0 or not config[1](prefix):
            raise HTTPException(status_code=400, detail="Image content does not match its declared type")
        return size, digest.hexdigest(), mime_type
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        await file.close()


def register_test_case_image_routes(app) -> None:
    @app.get("/test-suites/{test_suite_id}/test-case-image-counts")
    def test_case_image_counts(
        test_suite_id: int,
        db: Session = Depends(get_db),
        current_user: schemas.User = Depends(get_current_active_user),
    ):
        suite = db.query(models.TestSuite).filter(models.TestSuite.id == test_suite_id).first()
        if suite is None:
            raise HTTPException(status_code=404, detail="Test suite not found")
        if not rbac.has_permission(current_user, "read", suite.project_id, db):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        rows = db.query(
            models.TestCaseImage.test_case_id,
            func.count(models.TestCaseImage.id),
        ).join(models.TestCase, models.TestCase.id == models.TestCaseImage.test_case_id).filter(
            models.TestCase.test_suite_id == suite.id,
            models.TestCase.is_deleted.is_(False),
        ).group_by(models.TestCaseImage.test_case_id).all()
        return {str(test_case_id): count for test_case_id, count in rows}

    @app.get("/test-cases/{test_case_id}/images")
    def list_test_case_images(
        test_case_id: int,
        db: Session = Depends(get_db),
        current_user: schemas.User = Depends(get_current_active_user),
    ):
        test_case = _case_or_404(db, test_case_id)
        _require(db, current_user, test_case, "read")
        rows = db.query(models.TestCaseImage).filter(
            models.TestCaseImage.test_case_id == test_case.id,
        ).order_by(models.TestCaseImage.created_at, models.TestCaseImage.id).all()
        return [_view(row) for row in rows]

    @app.post("/test-cases/{test_case_id}/images", status_code=201)
    async def upload_test_case_image(
        test_case_id: int,
        file: UploadFile = File(...),
        test_step_id: int | None = Form(None),
        alt_text: str | None = Form(None, max_length=500),
        db: Session = Depends(get_db),
        current_user: schemas.User = Depends(get_current_active_user),
    ):
        test_case = _case_or_404(db, test_case_id)
        _require(db, current_user, test_case, "write")
        if test_step_id is not None and not db.query(models.TestCaseStep).filter(
            models.TestCaseStep.id == test_step_id,
            models.TestCaseStep.test_case_id == test_case.id,
        ).first():
            raise HTTPException(status_code=400, detail="Test step does not belong to this test case")
        mime_type = (file.content_type or "").lower()
        suffix = IMAGE_TYPES.get(mime_type, ("", None))[0]
        storage_key = f"{uuid.uuid4().hex}{suffix}"
        destination = _image_path(test_case, storage_key)
        size, digest, mime_type = await _write_image(file, destination)
        row = models.TestCaseImage(
            test_case_id=test_case.id,
            test_step_id=test_step_id,
            filename=re.sub(r"[\x00-\x1f\\/]", "_", file.filename or f"image{suffix}")[:255],
            storage_key=storage_key,
            mime_type=mime_type,
            file_size=size,
            sha256=digest,
            alt_text=(alt_text or "").strip() or None,
            uploaded_by=current_user.id,
        )
        try:
            db.add(row)
            db.commit()
            db.refresh(row)
        except Exception:
            db.rollback()
            destination.unlink(missing_ok=True)
            raise
        return _view(row)

    @app.put("/test-cases/{test_case_id}/images/{image_id}")
    async def replace_test_case_image(
        test_case_id: int,
        image_id: int,
        file: UploadFile = File(...),
        alt_text: str | None = Form(None, max_length=500),
        db: Session = Depends(get_db),
        current_user: schemas.User = Depends(get_current_active_user),
    ):
        test_case = _case_or_404(db, test_case_id)
        _require(db, current_user, test_case, "write")
        row = db.query(models.TestCaseImage).filter(
            models.TestCaseImage.id == image_id,
            models.TestCaseImage.test_case_id == test_case.id,
        ).first()
        if row is None:
            raise HTTPException(status_code=404, detail="Test case image not found")
        mime_type = (file.content_type or "").lower()
        suffix = IMAGE_TYPES.get(mime_type, ("", None))[0]
        storage_key = f"{uuid.uuid4().hex}{suffix}"
        destination = _image_path(test_case, storage_key)
        size, digest, mime_type = await _write_image(file, destination)
        old_path = _image_path(test_case, row.storage_key)
        row.storage_key = storage_key
        row.filename = re.sub(r"[\x00-\x1f\\/]", "_", file.filename or f"image{suffix}")[:255]
        row.mime_type = mime_type
        row.file_size = size
        row.sha256 = digest
        row.alt_text = (alt_text or "").strip() or row.alt_text
        try:
            db.commit()
            db.refresh(row)
        except Exception:
            db.rollback()
            destination.unlink(missing_ok=True)
            raise
        old_path.unlink(missing_ok=True)
        return _view(row)

    @app.get("/test-cases/{test_case_id}/images/{image_id}/content")
    def download_test_case_image(
        test_case_id: int,
        image_id: int,
        db: Session = Depends(get_db),
        current_user: schemas.User = Depends(get_current_active_user),
    ):
        test_case = _case_or_404(db, test_case_id)
        _require(db, current_user, test_case, "read")
        row = db.query(models.TestCaseImage).filter(
            models.TestCaseImage.id == image_id,
            models.TestCaseImage.test_case_id == test_case.id,
        ).first()
        if row is None:
            raise HTTPException(status_code=404, detail="Test case image not found")
        path = _image_path(test_case, row.storage_key)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Test case image file is unavailable")
        return FileResponse(path, media_type=row.mime_type, filename=row.filename)

    @app.delete("/test-cases/{test_case_id}/images/{image_id}", status_code=204)
    def delete_test_case_image(
        test_case_id: int,
        image_id: int,
        db: Session = Depends(get_db),
        current_user: schemas.User = Depends(get_current_active_user),
    ):
        test_case = _case_or_404(db, test_case_id)
        _require(db, current_user, test_case, "write")
        row = db.query(models.TestCaseImage).filter(
            models.TestCaseImage.id == image_id,
            models.TestCaseImage.test_case_id == test_case.id,
        ).first()
        if row is None:
            raise HTTPException(status_code=404, detail="Test case image not found")
        path = _image_path(test_case, row.storage_key)
        db.delete(row)
        db.commit()
        path.unlink(missing_ok=True)
        return None
