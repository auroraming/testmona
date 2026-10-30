from tests.backend.conftest import make_http_client


client = make_http_client()


def _seed_case(client):
    from app import models

    with client.SessionLocal() as db:
        suite = models.TestSuite(name="Images", project_id=client.project_id)
        db.add(suite)
        db.flush()
        case = models.TestCase(
            title="Image case", test_suite_id=suite.id, project_id=client.project_id,
            status="active", priority="medium", test_type="manual",
        )
        db.add(case)
        db.flush()
        step = models.TestCaseStep(
            test_case_id=case.id, step_number=1, order_index=0,
            action="Open page", expected_result="Page opens", step_type="manual",
        )
        db.add(step)
        db.commit()
        return suite.id, case.id, step.id


def test_case_image_upload_replace_download_and_delete(client, tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_CASE_IMAGE_DIR", str(tmp_path))
    suite_id, case_id, step_id = _seed_case(client)
    png = b"\x89PNG\r\n\x1a\nfixture"
    uploaded = client.post(
        f"/test-cases/{case_id}/images",
        data={"test_step_id": str(step_id), "alt_text": "Checkout screenshot"},
        files={"file": ("checkout.png", png, "image/png")},
    )
    assert uploaded.status_code == 201, uploaded.text
    image = uploaded.json()
    assert image["test_step_id"] == step_id
    assert image["alt_text"] == "Checkout screenshot"
    assert image["sha256"]

    counts = client.get(f"/test-suites/{suite_id}/test-case-image-counts")
    assert counts.status_code == 200
    assert counts.json() == {str(case_id): 1}

    listed = client.get(f"/test-cases/{case_id}/images")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [image["id"]]
    content = client.get(image["content_url"])
    assert content.status_code == 200
    assert content.content == png

    jpeg = b"\xff\xd8\xffreplacement"
    replaced = client.put(
        f"/test-cases/{case_id}/images/{image['id']}",
        data={"alt_text": "Replacement"},
        files={"file": ("replacement.jpg", jpeg, "image/jpeg")},
    )
    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["alt_text"] == "Replacement"
    assert client.get(image["content_url"]).content == jpeg
    assert len([path for path in tmp_path.rglob("*") if path.is_file()]) == 1

    deleted = client.delete(f"/test-cases/{case_id}/images/{image['id']}")
    assert deleted.status_code == 204
    assert client.get(image["content_url"]).status_code == 404
    assert not [path for path in tmp_path.rglob("*") if path.is_file()]


def test_case_image_rejects_spoofed_content_and_cross_case_step(client, tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_CASE_IMAGE_DIR", str(tmp_path))
    _suite_id, case_id, _step_id = _seed_case(client)
    _other_suite_id, other_case_id, other_step_id = _seed_case(client)
    response = client.post(
        f"/test-cases/{case_id}/images",
        data={"test_step_id": str(other_step_id)},
        files={"file": ("wrong.png", b"not-a-png", "image/png")},
    )
    assert response.status_code == 400
    assert "does not belong" in response.json()["detail"]
    spoofed = client.post(
        f"/test-cases/{other_case_id}/images",
        files={"file": ("wrong.png", b"not-a-png", "image/png")},
    )
    assert spoofed.status_code == 400
    assert "does not match" in spoofed.json()["detail"]
    assert not [path for path in tmp_path.rglob("*") if path.is_file()]

    from app import models
    with client.SessionLocal() as db:
        outsider = models.User(
            username="image-outsider", email="image-outsider@example.test",
            hashed_password="x", role="user", is_active=True,
        )
        db.add(outsider)
        db.commit()
        db.refresh(outsider)
        outsider_id = outsider.id
    client.set_current_user(outsider_id)
    assert client.get(f"/test-cases/{case_id}/images").status_code == 403
