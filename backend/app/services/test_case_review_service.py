"""Shared re-review policy hooks for test-case content mutations."""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .. import models


CONTENT_FIELDS = {"title", "preconditions", "steps", "expected_result"}


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
