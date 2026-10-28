"""MCP protocol and REST bridge tests."""

import json
import subprocess
import sys
from pathlib import Path


BACKEND = Path(__file__).resolve().parents[3] / "backend"
sys.path.insert(0, str(BACKEND))

from mcp_server import TOOLS, TestMonaClient, call_tool, handle_message  # noqa: E402


class FakeClient:
    def __init__(self):
        self.calls = []

    def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        return {"ok": True, "method": method, "path": path}


def test_tools_are_unique_and_cover_new_capabilities():
    names = [tool["name"] for tool in TOOLS]
    assert len(names) == len(set(names))
    assert {
        "list_test_case_directories",
        "link_mindmap_node_test_cases",
        "preview_openapi_test_cases",
        "commit_openapi_test_cases",
        "set_default_language",
    }.issubset(names)


def test_mcp_initialize_and_list_tools():
    client = FakeClient()
    initialized = handle_message({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}, client)
    assert initialized["result"]["serverInfo"]["name"] == "testmona"
    listed = handle_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, client)
    assert len(listed["result"]["tools"]) == len(TOOLS)


def test_tool_calls_map_to_scoped_rest_endpoints():
    client = FakeClient()
    call_tool(client, "list_test_case_directories", {"project_id": 7})
    call_tool(client, "move_test_cases_to_directory", {"test_case_ids": [1, 2], "section_id": 9})
    call_tool(client, "link_mindmap_node_test_cases", {"mindmap_id": 3, "node_id": "API/Auth", "test_case_ids": [1]})
    assert client.calls[0][:2] == ("GET", "/projects/7/sections/hierarchy")
    assert client.calls[1] == ("PATCH", "/test-cases/bulk", {"json_body": {"ids": [1, 2], "section_id": 9}})
    assert client.calls[2][1] == "/test-mindmaps/3/nodes/API%2FAuth/test-cases"


def test_language_tools_use_validated_system_setting_endpoint():
    client = FakeClient()
    call_tool(client, "get_default_language", {})
    call_tool(client, "set_default_language", {"language": "zh-CN"})
    assert client.calls[0][:2] == ("GET", "/system/settings/public/default_language")
    assert client.calls[1] == (
        "PUT",
        "/system/settings/default_language",
        {"json_body": {"value": "zh-CN"}},
    )


def test_openapi_preview_is_multipart_and_commit_defaults_to_skip():
    client = FakeClient()
    call_tool(client, "preview_openapi_test_cases", {"project_id": 4, "document": "openapi: 3.0.3", "filename": "api.yaml"})
    preview = client.calls[-1]
    assert preview[:2] == ("POST", "/import-export/openapi/preview")
    assert preview[2]["data"] == {"project_id": "4"}
    assert preview[2]["files"]["file"][0] == "api.yaml"

    call_tool(client, "commit_openapi_test_cases", {"project_id": 4, "test_suite_id": 2, "drafts": [{"title": "x"}]})
    assert client.calls[-1][2]["json_body"]["duplicate_mode"] == "skip"


def test_stdio_server_handles_handshake_without_token():
    process = subprocess.run(
        [sys.executable, str(BACKEND / "mcp_server.py")],
        input=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}) + "\n",
        text=True,
        capture_output=True,
        timeout=5,
        check=True,
    )
    response = json.loads(process.stdout.strip())
    assert response["id"] == 1
    assert response["result"]["capabilities"]["tools"] == {"listChanged": False}
