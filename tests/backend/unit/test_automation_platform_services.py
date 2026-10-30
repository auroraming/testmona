"""Pure policy, archive, budget, device, and discovery behavior."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.services.ai_manager import _usage_from_openai_payload
from app.services.automation_budget import budget_levels
from app.services.automation_devices import acquire_lock, apply_offline_reclaim, release_lock
from app.services.automation_openapi_scripts import materialize_api_scripts
from app.services.automation_policy import enforce_task_policy
from app.services.automation_results import API_RESULT_SCHEMA, archive_terminal_status, normalize_api_result
from app.services.automation_script_drafts import fixed_script_from_evidence
from app.services.mobile_mcp_discovery import discovery_contract, validate_mobile_mcp_package


def test_archive_requires_explicit_passing_assertions():
    evidence = [SimpleNamespace(evidence_type="step", status="completed", payload={})]
    assert archive_terminal_status("passed", {}, evidence) == ("failed", "missing_assertion")
    assert archive_terminal_status("passed", {"assertions": [{"passed": False}]}, []) == ("failed", "assertion_failed")
    assert archive_terminal_status("passed", {"assertions": [{"passed": True}]}, evidence) == ("passed", None)
    assert archive_terminal_status("failed", {}, []) == ("failed", None)
    assert archive_terminal_status("cancelled", None, []) == ("cancelled", None)


def test_native_and_mcp_results_share_one_shape():
    native = normalize_api_result("native_http", {
        "passed": True,
        "assertions": [{"name": "status", "passed": True, "expected": 200, "actual": 200}],
        "completed_steps": 2,
    })
    mcp = normalize_api_result("api_mcp", {
        "ok": True,
        "assertions": [{"name": "status", "passed": True, "expected": 200, "actual": 200}],
        "completed_steps": 2,
    })
    assert native["schema"] == mcp["schema"] == API_RESULT_SCHEMA
    assert native["passed"] is True and mcp["passed"] is True
    assert native["assertions"] == mcp["assertions"]
    assert normalize_api_result("api_mcp", {"ok": True, "assertions": []})["passed"] is False


def test_provider_cache_tokens_are_recorded_without_a_price():
    prompt, completion, cached = _usage_from_openai_payload({
        "usage": {"prompt_tokens": 20, "completion_tokens": 5, "prompt_tokens_details": {"cached_tokens": 7}},
    })
    assert (prompt, completion, cached) == (20, 5, 7)
    assert _usage_from_openai_payload({"usage": {"prompt_tokens": 1, "completion_tokens": 1}})[2] == 0


def test_budget_alerts_do_not_invent_a_price():
    assert budget_levels(1000, 700, 50) == []
    assert budget_levels(1000, 700, 100) == [("warning", "0.8")]
    assert budget_levels(1000, 900, 200) == [("exceeded", "1")]
    assert budget_levels(None, 10, 10) == []


def test_policy_denies_production_and_payment_targets():
    with pytest.raises(HTTPException) as production:
        enforce_task_policy({}, "production")
    assert production.value.status_code == 403
    with pytest.raises(HTTPException) as payment:
        enforce_task_policy({"base_url": "https://payments.example.test"}, None)
    assert payment.value.status_code == 403
    with pytest.raises(HTTPException) as destructive:
        enforce_task_policy({"script": [{"action": "request", "method": "DELETE", "path": "/items/1"}]}, None)
    assert destructive.value.status_code == 422
    allowed = enforce_task_policy({
        "base_url": "https://staging.example.test",
        "account_ref": "qa-bot",
        "script": [{"action": "request", "method": "DELETE", "path": "/items/1"}],
        "allowlist": {
            "origins": ["https://staging.example.test"],
            "accounts": ["qa-bot"],
            "networks": ["example.test"],
            "destructive_operations": ["DELETE /items/1"],
        },
    }, "staging")
    assert "https://staging.example.test" in allowed["origins"]


def test_openapi_script_omits_secret_examples_and_keeps_status_assertion():
    generated = materialize_api_scripts({
        "openapi": "3.0.3",
        "info": {"title": "Demo", "version": "1"},
        "paths": {
            "/health": {
                "get": {
                    "parameters": [{"name": "api_key", "in": "header", "example": "super-secret-value"}],
                    "responses": {"200": {"description": "ok"}},
                    "security": [{"bearer": []}],
                }
            }
        },
    }, "api-token")
    text = str(generated)
    assert "super-secret-value" not in text
    assert generated["scripts"][0]["script"][1] == {"action": "assert_status", "expected": 200}
    assert generated["scripts"][0]["auth"] == {"type": "bearer", "credential_ref": "api-token"}
    with pytest.raises(HTTPException):
        materialize_api_scripts({
            "openapi": "3.0.3",
            "info": {"title": "Demo", "version": "1"},
            "paths": {"/a": {"get": {"responses": {"200": {"description": "ok"}}, "parameters": [{"$ref": "https://evil.example/schema"}]}}},
        }, None)


def test_openapi_script_materializes_local_response_schema_for_the_api_runner():
    generated = materialize_api_scripts({
        "openapi": "3.0.3",
        "info": {"title": "Catalog", "version": "1"},
        "paths": {"/items": {"get": {"responses": {"200": {
            "description": "ok",
            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ItemList"}}},
        }}}}},
        "components": {"schemas": {"ItemList": {
            "type": "object",
            "required": ["items"],
            "properties": {"items": {"type": "array", "items": {"$ref": "#/components/schemas/Item"}}},
        }, "Item": {
            "type": "object", "required": ["id"], "properties": {"id": {"type": "integer"}},
        }}},
    })
    schema_step = generated["scripts"][0]["script"][2]
    assert schema_step["action"] == "assert_json_schema"
    assert schema_step["schema"]["properties"]["items"]["items"]["required"] == ["id"]


def test_swagger_response_schema_is_added_to_generated_script():
    generated = materialize_api_scripts({
        "swagger": "2.0",
        "info": {"title": "Health", "version": "1"},
        "paths": {"/health": {"get": {"responses": {"200": {
            "description": "ok", "schema": {"type": "object", "required": ["healthy"],
            "properties": {"healthy": {"type": "boolean"}}},
        }}}}},
    })
    assert generated["scripts"][0]["script"][2] == {
        "action": "assert_json_schema",
        "schema": {"type": "object", "required": ["healthy"], "properties": {"healthy": {"type": "boolean"}}},
    }


def test_reviewed_api_script_keeps_header_and_schema_assertions():
    schema = {"type": "object", "required": ["id"], "properties": {"id": {"type": "integer"}}}
    steps, warnings = fixed_script_from_evidence(
        execution_mode="script",
        config={"script": [
            {"action": "request", "method": "GET", "path": "/items"},
            {"action": "assert_header", "name": "x-version", "expected": "1"},
            {"action": "assert_json_schema", "schema": schema},
        ]},
        evidence=[],
    )
    assert warnings == []
    assert steps[1] == {"action": "assert_header", "name": "x-version", "expected": "1"}
    assert steps[2] == {"action": "assert_json_schema", "schema": schema}


def test_device_lock_is_exclusive_and_offline_reclaim_clears_it():
    now = datetime.now(timezone.utc)
    device = SimpleNamespace(
        status="online", last_seen_at=now, lock_task_id=None, lock_runner_id=None, lock_expires_at=None,
    )
    acquire_lock(device, task_id=7, runner_id=3, now=now)
    assert device.status == "locked"
    with pytest.raises(PermissionError):
        acquire_lock(device, task_id=8, runner_id=4, now=now)
    device.last_seen_at = now - timedelta(seconds=120)
    assert apply_offline_reclaim(device, now) is True
    assert device.status == "offline"
    assert device.lock_task_id is None


def test_release_lock_is_idempotent_for_the_holder():
    device = SimpleNamespace(status="locked", lock_task_id=7, lock_runner_id=3, lock_expires_at=None)
    assert release_lock(device, task_id=7, runner_id=3) is True
    assert release_lock(device, task_id=7, runner_id=3) is False


def test_mobile_discovery_contract_hides_unlisted_tools():
    with pytest.raises(ValueError):
        validate_mobile_mcp_package("@mobilenext/mobile-mcp@latest")
    assert validate_mobile_mcp_package("@mobilenext/mobile-mcp@1.2.3") == "@mobilenext/mobile-mcp@1.2.3"
    contract = discovery_contract(None)
    assert contract["live"] is False
    assert "mobile_install_app" not in contract["tools"]
    filtered = discovery_contract(["mobile_list_available_devices", "mobile_install_app"])
    assert filtered["tools"] == ["mobile_list_available_devices"]
    assert filtered["hidden_tools"] == ["mobile_install_app"]
