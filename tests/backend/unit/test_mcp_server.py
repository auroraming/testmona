"""Remote FastMCP surface tests."""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import httpx2
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.server.auth import AccessToken
from fastmcp.utilities.asgi_transport import StreamingASGITransport


BACKEND = Path(__file__).resolve().parents[3] / "backend"
sys.path.insert(0, str(BACKEND))

import app.mcp_server as mcp_module  # noqa: E402
from app.main import app  # noqa: E402


EXPECTED_TOOLS = {
    "get_default_language",
    "set_default_language",
    "list_test_case_directories",
    "create_test_case_directory",
    "update_test_case_directory",
    "move_test_cases_to_directory",
    "list_mindmaps",
    "get_mindmap",
    "create_mindmap",
    "update_mindmap",
    "list_mindmap_node_test_cases",
    "link_mindmap_node_test_cases",
    "unlink_mindmap_node_test_case",
    "list_test_case_mindmaps",
    "preview_openapi_test_cases",
    "commit_openapi_test_cases",
    "create_ai_automation_task",
    "list_ai_automation_tasks",
    "get_ai_automation_task",
    "cancel_ai_automation_task",
    "list_ai_automation_evidence",
}


@pytest.mark.asyncio
async def test_remote_server_exposes_unique_curated_tools():
    server = mcp_module.create_mcp_server(lambda: app)
    tools = await server.list_tools()
    names = [tool.name for tool in tools]

    assert len(names) == len(set(names))
    assert set(names) == EXPECTED_TOOLS


@pytest.mark.asyncio
async def test_tool_calls_reuse_scoped_rest_routes(monkeypatch):
    calls = []

    async def fake_request(_self, method, path, **kwargs):
        calls.append((method, path, kwargs))
        return {"ok": True}

    monkeypatch.setattr(mcp_module.TestMonaASGIClient, "request", fake_request)
    server = mcp_module.create_mcp_server(lambda: app)

    move = await server.get_tool("move_test_cases_to_directory")
    link = await server.get_tool("link_mindmap_node_test_cases")
    language = await server.get_tool("set_default_language")
    await move.run({"test_case_ids": [1, 2], "section_id": 9})
    await link.run({"mindmap_id": 3, "node_id": "API/Auth", "test_case_ids": [1]})
    await language.run({"language": "zh-CN"})

    assert calls[0] == (
        "PATCH",
        "/test-cases/bulk",
        {"json_body": {"ids": [1, 2], "section_id": 9}},
    )
    assert calls[1][1] == "/test-mindmaps/3/nodes/API%2FAuth/test-cases"
    assert calls[2] == (
        "PUT",
        "/system/settings/default_language",
        {"json_body": {"value": "zh-CN"}},
    )


@pytest.mark.asyncio
async def test_openapi_preview_is_multipart_and_commit_defaults_to_skip(monkeypatch):
    calls = []

    async def fake_request(_self, method, path, **kwargs):
        calls.append((method, path, kwargs))
        return {"ok": True}

    monkeypatch.setattr(mcp_module.TestMonaASGIClient, "request", fake_request)
    server = mcp_module.create_mcp_server(lambda: app)
    preview = await server.get_tool("preview_openapi_test_cases")
    commit = await server.get_tool("commit_openapi_test_cases")

    await preview.run({"project_id": 4, "document": "openapi: 3.0.3", "filename": "api.yaml"})
    await commit.run({"project_id": 4, "test_suite_id": 2, "drafts": [{"title": "x"}]})

    assert calls[0][0:2] == ("POST", "/import-export/openapi/preview")
    assert calls[0][2]["data"] == {"project_id": "4"}
    assert calls[0][2]["files"]["file"][0] == "api.yaml"
    assert calls[1][2]["json_body"]["duplicate_mode"] == "skip"


@pytest.mark.asyncio
async def test_ai_automation_tools_reuse_scoped_task_routes(monkeypatch):
    calls = []

    async def fake_request(_self, method, path, **kwargs):
        calls.append((method, path, kwargs))
        return {"ok": True}

    monkeypatch.setattr(mcp_module.TestMonaASGIClient, "request", fake_request)
    server = mcp_module.create_mcp_server(lambda: app)
    create = await server.get_tool("create_ai_automation_task")
    evidence = await server.get_tool("list_ai_automation_evidence")

    await create.run({
        "project_id": 4,
        "runner_type": "api",
        "goal": "Verify health endpoint",
        "token_budget": 1000,
    })
    await evidence.run({"task_id": 9})

    assert calls[0][0:2] == ("POST", "/ai-automation/tasks")
    assert calls[0][2]["json_body"]["runner_type"] == "api"
    assert calls[0][2]["json_body"]["token_budget"] == 1000
    assert calls[1] == ("GET", "/ai-automation/tasks/9/evidence", {})


@pytest.mark.asyncio
async def test_token_verifier_uses_existing_personal_token_validation(monkeypatch):
    closed = []

    class FakeDB:
        def close(self):
            closed.append(True)

    monkeypatch.setattr(mcp_module, "SessionLocal", FakeDB)
    monkeypatch.setattr(
        mcp_module,
        "get_user_for_token",
        lambda _db, raw: SimpleNamespace(
            id=7,
            username="ming",
            role="admin",
            is_superuser=True,
        )
        if raw == "tmona_valid"
        else None,
    )

    verifier = mcp_module.TestMonaTokenVerifier()
    access_token = await verifier.verify_token("tmona_valid")

    assert access_token is not None
    assert access_token.claims["sub"] == "7"
    assert access_token.claims["username"] == "ming"
    assert await verifier.verify_token("invalid") is None
    assert len(closed) == 2


def test_fastapi_mounts_only_remote_mcp_endpoint():
    mount_paths = [route.path for route in app.routes if route.__class__.__name__ == "Mount"]
    assert "/mcp" in mount_paths
    assert not (BACKEND / "mcp_server.py").exists()


@pytest.mark.asyncio
async def test_remote_http_handshake_requires_and_accepts_bearer_token(monkeypatch):
    async def verify(_self, raw_token):
        if raw_token != "tmona_valid":
            return None
        return AccessToken(
            token=raw_token,
            client_id="test-client",
            scopes=["testmona:mcp"],
            claims={"iss": "testmona", "sub": "7"},
        )

    monkeypatch.setattr(mcp_module.TestMonaTokenVerifier, "verify_token", verify)

    def http_client_factory(**kwargs):
        return httpx2.AsyncClient(transport=StreamingASGITransport(app), **kwargs)

    async with app.router.lifespan_context(app):
        valid_transport = StreamableHttpTransport(
            url="http://testserver/mcp",
            auth="tmona_valid",
            httpx_client_factory=http_client_factory,
        )
        async with Client(valid_transport) as client:
            assert {tool.name for tool in await client.list_tools()} == EXPECTED_TOOLS

        invalid_transport = StreamableHttpTransport(
            url="http://testserver/mcp",
            auth="not-valid",
            httpx_client_factory=http_client_factory,
        )
        with pytest.raises(Exception):
            async with Client(invalid_transport):
                pass
