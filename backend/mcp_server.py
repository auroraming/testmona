#!/usr/bin/env python3
"""TestMona MCP stdio server.

Configuration:
  TESTMONA_URL       Backend URL (default: http://127.0.0.1:8000)
  TESTMONA_API_TOKEN Personal API token created in TestMona (tmona_...)

The server intentionally delegates authorization and validation to TestMona's
HTTP API. It never opens the database and therefore cannot bypass RBAC.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any
from urllib.parse import quote

import requests


PROTOCOL_VERSION = "2025-03-26"


class TestMonaAPIError(RuntimeError):
    pass


class TestMonaClient:
    def __init__(self, base_url: str | None = None, token: str | None = None):
        self.base_url = (base_url or os.getenv("TESTMONA_URL") or "http://127.0.0.1:8000").rstrip("/")
        self.token = token or os.getenv("TESTMONA_API_TOKEN") or ""

    def request(self, method: str, path: str, *, params: dict | None = None,
                json_body: Any = None, files: dict | None = None, data: dict | None = None) -> Any:
        if not self.token:
            raise TestMonaAPIError("TESTMONA_API_TOKEN is required. Create a personal API token in TestMona settings.")
        response = requests.request(
            method,
            f"{self.base_url}{path}",
            params=params,
            json=json_body,
            files=files,
            data=data,
            headers={"Authorization": f"Bearer {self.token}"},
            timeout=300,
        )
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail", response.text)
            except ValueError:
                detail = response.text
            raise TestMonaAPIError(f"TestMona API {response.status_code}: {detail}")
        if response.status_code == 204 or not response.content:
            return {"ok": True}
        return response.json()


def _obj(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "object", "properties": properties, "additionalProperties": False}
    if required:
        schema["required"] = required
    return schema


TOOLS = [
    {"name": "get_default_language", "description": "Read the instance default UI language.", "inputSchema": _obj({})},
    {"name": "set_default_language", "description": "Set the instance default UI language. Requires an administrator API token.", "inputSchema": _obj({"language": {"type": "string", "enum": ["en", "fa", "ar", "zh-CN"]}}, ["language"])},
    {"name": "list_test_case_directories", "description": "List test suites and their hierarchical test-case directories with direct, descendant, and total case counts.", "inputSchema": _obj({"project_id": {"type": "integer", "minimum": 1}}, ["project_id"])},
    {"name": "create_test_case_directory", "description": "Create a test-case directory in a test suite.", "inputSchema": _obj({"test_suite_id": {"type": "integer", "minimum": 1}, "name": {"type": "string", "minLength": 1, "maxLength": 255}, "description": {"type": "string"}, "parent_section_id": {"type": ["integer", "null"], "minimum": 1}}, ["test_suite_id", "name"])},
    {"name": "update_test_case_directory", "description": "Rename, describe, reorder, or move a test-case directory within its suite.", "inputSchema": _obj({"section_id": {"type": "integer", "minimum": 1}, "name": {"type": "string"}, "description": {"type": ["string", "null"]}, "parent_section_id": {"type": ["integer", "null"]}, "order_index": {"type": "integer"}}, ["section_id"])},
    {"name": "move_test_cases_to_directory", "description": "Move test cases to a directory. All cases and the directory must belong to the same test suite.", "inputSchema": _obj({"test_case_ids": {"type": "array", "minItems": 1, "maxItems": 2000, "items": {"type": "integer"}}, "section_id": {"type": "integer", "minimum": 1}}, ["test_case_ids", "section_id"])},
    {"name": "list_mindmaps", "description": "List mind maps in a project.", "inputSchema": _obj({"project_id": {"type": "integer", "minimum": 1}}, ["project_id"])},
    {"name": "get_mindmap", "description": "Get a mind map and its versioned node data.", "inputSchema": _obj({"mindmap_id": {"type": "integer", "minimum": 1}}, ["mindmap_id"])},
    {"name": "create_mindmap", "description": "Create a mind map. mindmap_data may contain version, rootId, and nodes.", "inputSchema": _obj({"project_id": {"type": "integer", "minimum": 1}, "name": {"type": "string", "minLength": 1}, "description": {"type": "string"}, "mindmap_data": {"type": "object"}}, ["project_id", "name"])},
    {"name": "update_mindmap", "description": "Update a mind map's name, description, or node data. Links for removed nodes are cleaned automatically.", "inputSchema": _obj({"mindmap_id": {"type": "integer", "minimum": 1}, "name": {"type": "string"}, "description": {"type": ["string", "null"]}, "mindmap_data": {"type": "object"}}, ["mindmap_id"])},
    {"name": "list_mindmap_node_test_cases", "description": "List test cases linked to a mind-map node.", "inputSchema": _obj({"mindmap_id": {"type": "integer", "minimum": 1}, "node_id": {"type": "string", "minLength": 1}}, ["mindmap_id", "node_id"])},
    {
        "name": "link_mindmap_node_test_cases",
        "description": "Idempotently link project test cases to a mind-map node.",
        "inputSchema": _obj(
            {
                "mindmap_id": {"type": "integer", "minimum": 1},
                "node_id": {"type": "string", "minLength": 1},
                "test_case_ids": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"type": "integer"},
                },
            },
            ["mindmap_id", "node_id", "test_case_ids"],
        ),
    },
    {"name": "unlink_mindmap_node_test_case", "description": "Remove one test-case link from a mind-map node.", "inputSchema": _obj({"mindmap_id": {"type": "integer", "minimum": 1}, "node_id": {"type": "string", "minLength": 1}, "test_case_id": {"type": "integer", "minimum": 1}}, ["mindmap_id", "node_id", "test_case_id"])},
    {"name": "list_test_case_mindmaps", "description": "List mind maps and nodes linked to a test case.", "inputSchema": _obj({"test_case_id": {"type": "integer", "minimum": 1}}, ["test_case_id"])},
    {"name": "preview_openapi_test_cases", "description": "Safely parse OpenAPI 3.x JSON/YAML text and preview generated test cases without writing data.", "inputSchema": _obj({"project_id": {"type": "integer", "minimum": 1}, "document": {"type": "string", "minLength": 1}, "filename": {"type": "string", "pattern": "\\.(json|yaml|yml)$"}}, ["project_id", "document"])},
    {
        "name": "commit_openapi_test_cases",
        "description": "Create selected OpenAPI preview drafts in a suite/directory after human review.",
        "inputSchema": _obj(
            {
                "project_id": {"type": "integer", "minimum": 1},
                "test_suite_id": {"type": "integer", "minimum": 1},
                "section_id": {"type": ["integer", "null"]},
                "duplicate_mode": {"type": "string", "enum": ["skip", "copy"]},
                "drafts": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 1000,
                    "items": {"type": "object"},
                },
            },
            ["project_id", "test_suite_id", "drafts"],
        ),
    },
]


def call_tool(client: TestMonaClient, name: str, args: dict[str, Any]) -> Any:
    a = dict(args or {})
    if name == "get_default_language":
        return client.request("GET", "/system/settings/public/default_language")
    if name == "set_default_language":
        return client.request("PUT", "/system/settings/default_language", json_body={"value": a["language"]})
    if name == "list_test_case_directories":
        return client.request("GET", f"/projects/{a['project_id']}/sections/hierarchy")
    if name == "create_test_case_directory":
        return client.request("POST", "/sections/", json_body=a)
    if name == "update_test_case_directory":
        section_id = a.pop("section_id")
        return client.request("PUT", f"/sections/{section_id}", json_body=a)
    if name == "move_test_cases_to_directory":
        return client.request("PATCH", "/test-cases/bulk", json_body={"ids": a["test_case_ids"], "section_id": a["section_id"]})
    if name == "list_mindmaps":
        return client.request("GET", "/test-mindmaps/", params={"project_id": a["project_id"]})
    if name == "get_mindmap":
        return client.request("GET", f"/test-mindmaps/{a['mindmap_id']}")
    if name == "create_mindmap":
        a.setdefault("mindmap_data", {"version": 1, "rootId": "root", "nodes": [{"id": "root", "title": a["name"], "parentId": None}]})
        return client.request("POST", "/test-mindmaps/", json_body=a)
    if name == "update_mindmap":
        mindmap_id = a.pop("mindmap_id")
        return client.request("PUT", f"/test-mindmaps/{mindmap_id}", json_body=a)
    if name == "list_mindmap_node_test_cases":
        node_id = quote(str(a["node_id"]), safe="")
        return client.request("GET", f"/test-mindmaps/{a['mindmap_id']}/nodes/{node_id}/test-cases")
    if name == "link_mindmap_node_test_cases":
        node_id = quote(str(a["node_id"]), safe="")
        return client.request("POST", f"/test-mindmaps/{a['mindmap_id']}/nodes/{node_id}/test-cases", json_body={"test_case_ids": a["test_case_ids"]})
    if name == "unlink_mindmap_node_test_case":
        node_id = quote(str(a["node_id"]), safe="")
        return client.request("DELETE", f"/test-mindmaps/{a['mindmap_id']}/nodes/{node_id}/test-cases/{a['test_case_id']}")
    if name == "list_test_case_mindmaps":
        return client.request("GET", f"/test-cases/{a['test_case_id']}/mindmaps")
    if name == "preview_openapi_test_cases":
        filename = a.get("filename") or "openapi.yaml"
        return client.request("POST", "/import-export/openapi/preview", data={"project_id": str(a["project_id"])}, files={"file": (filename, a["document"].encode("utf-8"), "application/octet-stream")})
    if name == "commit_openapi_test_cases":
        a.setdefault("duplicate_mode", "skip")
        return client.request("POST", "/import-export/openapi/commit", json_body=a)
    raise TestMonaAPIError(f"Unknown MCP tool: {name}")


def handle_message(message: dict[str, Any], client: TestMonaClient) -> dict[str, Any] | None:
    method = message.get("method")
    request_id = message.get("id")
    if request_id is None:
        return None
    try:
        if method == "initialize":
            result = {"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {"listChanged": False}}, "serverInfo": {"name": "testmona", "version": "1.0.0"}}
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            params = message.get("params") or {}
            data = call_tool(client, params.get("name", ""), params.get("arguments") or {})
            result = {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False, default=str)}], "structuredContent": data}
        else:
            return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    except (KeyError, TypeError, ValueError, TestMonaAPIError) as exc:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32000, "message": str(exc)}}


def main() -> None:
    client = TestMonaClient()
    for line in sys.stdin:
        try:
            message = json.loads(line)
            response = handle_message(message, client)
        except Exception as exc:  # keep the stdio process alive on malformed input
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"Parse error: {exc}"}}
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
