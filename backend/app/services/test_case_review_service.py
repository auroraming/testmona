"""Shared re-review policy hooks for test-case content mutations."""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .. import models


CONTENT_FIELDS = {"title", "preconditions", "steps", "expected_result"}


def snapshot_test_case(db: Session, test_case: models.TestCase) -> tuple[int, dict]:
    """Capture the case content used by reviews and historical executions."""
    revision = db.query(models.TestCaseRevision.revision_number).filter(
        models.TestCaseRevision.test_case_id == test_case.id,
    ).order_by(models.TestCaseRevision.revision_number.desc()).limit(1).scalar() or 0
    steps = db.query(models.TestCaseStep).filter(
        models.TestCaseStep.test_case_id == test_case.id,
    ).order_by(models.TestCaseStep.order_index, models.TestCaseStep.step_number).all()
    images = db.query(models.TestCaseImage).filter(
        models.TestCaseImage.test_case_id == test_case.id,
    ).order_by(models.TestCaseImage.id).all()
    return revision, {
        "title": test_case.title,
        "description": test_case.description,
        "preconditions": test_case.preconditions,
        "steps": test_case.steps,
        "expected_result": test_case.expected_result,
        "priority": test_case.priority,
        "test_type": test_case.test_type,
        "structured_steps": [
            {
                "step_number": step.step_number,
                "action": step.action,
                "expected_result": step.expected_result,
                "step_type": step.step_type,
                "data": step.data,
            }
            for step in steps
        ],
        "images": [
            {
                "id": image.id,
                "test_step_id": image.test_step_id,
                "filename": image.filename,
                "mime_type": image.mime_type,
                "sha256": image.sha256,
                "alt_text": image.alt_text,
            }
            for image in images
        ],
    }


def mark_review_required(db: Session, test_case: models.TestCase, reason: str) -> bool:
    """Mark a reviewed case stale when its project policy is enabled.

    Completed review rounds remain immutable. The marker belongs to the current
    test-case content and is cleared only by approving a new round whose snapshot
    still matches the case.
    """
    project = test_case.project or db.query(models.Project).filter(models.Project.id == test_case.project_id).first()
    if project is None or not project.test_case_review_on_content_change:
        return False
    has_review = db.query(models.TestCaseReviewRound.id).filter(
        models.TestCaseReviewRound.test_case_id == test_case.id,
    ).first()
    if has_review is None:
        return False
    test_case.review_required = True
    test_case.review_required_at = datetime.now(timezone.utc)
    test_case.review_required_reason = reason[:100]
    db.add(test_case)
    db.commit()
    db.refresh(test_case)
    return True
