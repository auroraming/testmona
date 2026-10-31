from tests.backend.conftest import make_http_client, seed_admin_project_member


client = make_http_client(seed_fn=seed_admin_project_member)


def _seed_cases(client):
    from app import models

    with client.SessionLocal() as db:
        suite = models.TestSuite(name="Review suite", project_id=client.project_id)
        db.add(suite)
        db.flush()
        first = models.TestCase(
            title="Login succeeds", description="Original description", preconditions="Account exists",
            test_suite_id=suite.id, project_id=client.project_id, status="active", priority="high",
            test_type="manual", created_by=1,
        )
        second = models.TestCase(
            title="Login fails", test_suite_id=suite.id, project_id=client.project_id,
            status="active", priority="medium", test_type="manual", created_by=1,
        )
        db.add_all([first, second])
        db.flush()
        db.add(models.TestCaseStep(
            test_case_id=first.id, step_number=1, order_index=0,
            action="Submit credentials", expected_result="Dashboard opens", step_type="manual",
        ))
        reviewer = models.User(
            username="reviewer-two", email="reviewer-two@example.test", hashed_password="x",
            role="user", is_active=True, full_name="Reviewer Two",
        )
        outsider = models.User(
            username="review-outsider", email="review-outsider@example.test", hashed_password="x",
            role="user", is_active=True, full_name="Outsider",
        )
        db.add_all([reviewer, outsider])
        db.flush()
        db.add(models.ProjectAssignment(project_id=client.project_id, user_id=reviewer.id))
        db.commit()
        return suite.id, first.id, second.id, reviewer.id, outsider.id


def _create(client, suite_id, case_ids, reviewer_ids, mode="multiple"):
    return client.post("/test-case-review-tasks", json={
        "name": "Release review", "test_suite_id": suite_id, "test_case_ids": case_ids,
        "reviewer_ids": reviewer_ids, "mode": mode,
    })


def test_multi_reviewer_task_preserves_snapshot_and_rolls_up_status(client):
    suite_id, first_id, second_id, reviewer_id, _outsider_id = _seed_cases(client)
    created = _create(client, suite_id, [first_id, second_id], [client.member_id, reviewer_id])
    assert created.status_code == 201, created.text
    task = created.json()
    assert task["status"] == "pending"
    assert len(task["rounds"]) == 2
    first_round = next(item for item in task["rounds"] if item["test_case_id"] == first_id)
    assert first_round["snapshot"]["description"] == "Original description"
    assert first_round["snapshot"]["structured_steps"][0]["action"] == "Submit credentials"

    with client.SessionLocal() as db:
        from app import models
        notifications = db.query(models.Notification).filter(
            models.Notification.category == "review",
            models.Notification.related_entity_type == "test_case_review_task",
            models.Notification.related_entity_id == task["id"],
        ).all()
        assert {row.user_id for row in notifications} == {client.member_id, reviewer_id}
        audit = db.query(models.AuditTrail).filter(
            models.AuditTrail.project_id == client.project_id,
            models.AuditTrail.action == models.AuditAction.CREATE,
        ).one()
        assert audit.additional_metadata["review_task_id"] == task["id"]

    with client.SessionLocal() as db:
        from app import models
        case = db.query(models.TestCase).filter(models.TestCase.id == first_id).one()
        case.description = "Changed after submission"
        db.commit()

    client.set_current_user(client.member_id)
    approved = client.post(f"/test-case-review-rounds/{first_round['id']}/decision", json={
        "decision": "approved", "comment": "Looks good", "has_suggestion": True,
    })
    assert approved.status_code == 200, approved.text
    assert next(item for item in approved.json()["rounds"] if item["id"] == first_round["id"])["status"] == "pending"

    client.set_current_user(reviewer_id)
    rejected = client.post(f"/test-case-review-rounds/{first_round['id']}/decision", json={
        "decision": "changes_requested", "comment": "Add a boundary case",
    })
    assert rejected.status_code == 200, rejected.text
    body = rejected.json()
    assert body["status"] == "changes_requested"
    current = next(item for item in body["rounds"] if item["id"] == first_round["id"])
    assert current["status"] == "changes_requested"
    assert current["snapshot"]["description"] == "Original description"
    with client.SessionLocal() as db:
        from app import models
        assert db.query(models.Notification).filter(
            models.Notification.user_id == 1,
            models.Notification.related_entity_type == "test_case_review_task",
            models.Notification.related_entity_id == task["id"],
        ).count() == 2
        assert db.query(models.AuditTrail).filter(
            models.AuditTrail.project_id == client.project_id,
            models.AuditTrail.action.in_([models.AuditAction.APPROVE, models.AuditAction.REJECT]),
        ).count() == 2


def test_reviewer_changes_keep_history_and_rereview_creates_new_round(client):
    suite_id, first_id, _second_id, reviewer_id, _outsider_id = _seed_cases(client)
    created = _create(client, suite_id, [first_id], [client.member_id], mode="single")
    assert created.status_code == 201, created.text
    task = created.json()
    round_ = task["rounds"][0]

    changed = client.put(f"/test-case-review-rounds/{round_['id']}/reviewers", json={"reviewer_ids": [reviewer_id]})
    assert changed.status_code == 200, changed.text
    assignments = changed.json()["rounds"][0]["assignments"]
    assert next(item for item in assignments if item["reviewer_id"] == client.member_id)["is_active"] is False
    assert next(item for item in assignments if item["reviewer_id"] == reviewer_id)["is_active"] is True

    client.set_current_user(client.member_id)
    assert client.post(f"/test-case-review-rounds/{round_['id']}/decision", json={"decision": "approved"}).status_code == 403
    client.set_current_user(reviewer_id)
    decided = client.post(f"/test-case-review-rounds/{round_['id']}/decision", json={"decision": "approved"})
    assert decided.status_code == 200, decided.text
    assert decided.json()["status"] == "approved"

    client.set_current_user(1)
    rereview = client.post(f"/test-case-review-tasks/{task['id']}/rereview", json={"test_case_ids": [first_id]})
    assert rereview.status_code == 201, rereview.text
    body = rereview.json()
    assert body["status"] == "pending"
    assert [item["round_number"] for item in body["rounds"]] == [1, 2]
    assert body["rounds"][0]["status"] == "approved"
    assert body["rounds"][1]["assignments"][0]["reviewer_id"] == reviewer_id


def test_review_validates_scope_mode_and_reviewer_access(client):
    suite_id, first_id, _second_id, _reviewer_id, outsider_id = _seed_cases(client)
    invalid_mode = _create(client, suite_id, [first_id], [client.member_id, outsider_id], mode="single")
    assert invalid_mode.status_code == 400
    denied_reviewer = _create(client, suite_id, [first_id], [outsider_id], mode="single")
    assert denied_reviewer.status_code == 400
    assert denied_reviewer.json()["detail"]["reviewers_without_project_access"] == [outsider_id]

    from app import models
    with client.SessionLocal() as db:
        other_project = models.Project(name="Other review project", owner_id=1)
        db.add(other_project)
        db.flush()
        other_suite = models.TestSuite(name="Other suite", project_id=other_project.id)
        db.add(other_suite)
        db.flush()
        other_case = models.TestCase(
            title="Other case", test_suite_id=other_suite.id, project_id=other_project.id,
            status="active", priority="medium", test_type="manual",
        )
        db.add(other_case)
        db.commit()
        other_case_id = other_case.id
    cross_suite = _create(client, suite_id, [other_case_id], [client.member_id], mode="single")
    assert cross_suite.status_code == 400
    assert cross_suite.json()["detail"]["invalid_test_case_ids"] == [other_case_id]
