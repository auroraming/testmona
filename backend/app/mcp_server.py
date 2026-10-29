"""Remote FastMCP surface for TestMona.

The MCP tools re-enter the existing ASGI API in-process. This keeps the REST
permission checks, validation, and audit trail as the single source of truth
without opening a second network connection or bypassing application rules.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any
from urllib.parse import quote

import httpx
from fastapi import FastAPI
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AccessToken, TokenVerifier
from fastmcp.server.dependencies import get_access_token
from pydantic import Field, PositiveInt
from starlette.concurrency import run_in_threadpool

from .database import SessionLocal
from .services.api_token_service import get_user_for_token


class TestMonaTokenVerifier(TokenVerifier):
    """Validate existing TestMona personal API tokens for MCP requests."""

    async def verify_token(self, token: str) -> AccessToken | None:
        def resolve_user() -> dict[str, Any] | None:
            db = SessionLocal()
            try:
                user = get_user_for_token(db, token)
                if user is None:
                    return None
                return {
                    "id": user.id,
                    "username": user.username,
                    "role": user.role,
                    "is_superuser": bool(user.is_superuser),
                }
            finally:
                db.close()

        user = await run_in_threadpool(resolve_user)
        if user is None:
            return None
        return AccessToken(
            token=token,
            client_id="testmona-personal-token",
            scopes=["testmona:mcp"],
            claims={
                "iss": "testmona",
                "sub": str(user["id"]),
                **user,
            },
        )


class TestMonaASGIClient:
    def __init__(self, app_getter: Callable[[], FastAPI]):
        self._app_getter = app_getter

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        files: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> Any:
        access_token = get_access_token()
        if access_token is None:
            raise ToolError("Authentication is required")

        transport = httpx.ASGITransport(app=self._app_getter())
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testmona.internal",
            follow_redirects=True,
            timeout=300,
        ) as client:
            response = await client.request(
                method,
                path,
                params=params,
                json=json_body,
                files=files,
                data=data,
                headers={"Authorization": f"Bearer {access_token.token}"},
            )

        if response.status_code >= 400:
            try:
                payload = response.json()
                detail = payload.get("detail", payload)
            except ValueError:
                detail = response.text
            raise ToolError(f"TestMona API {response.status_code}: {detail}")
        if response.status_code == 204 or not response.content:
            return {"ok": True}
        return response.json()


def create_mcp_server(app_getter: Callable[[], FastAPI]) -> FastMCP:
    mcp = FastMCP(
        "TestMona",
        instructions="Manage TestMona test assets through the authenticated user's existing permissions.",
        auth=TestMonaTokenVerifier(),
    )
    api = TestMonaASGIClient(app_getter)

    @mcp.tool
    async def get_default_language() -> dict[str, Any]:
        """Read the instance default UI language."""
        return await api.request("GET", "/system/settings/public/default_language")

    @mcp.tool
    async def set_default_language(
        language: Annotated[str, Field(pattern=r"^(en|fa|ar|zh-CN)$")],
    ) -> dict[str, Any]:
        """Set the instance default UI language. Administrator permission is required."""
        return await api.request("PUT", "/system/settings/default_language", json_body={"value": language})

    @mcp.tool
    async def list_test_case_directories(project_id: PositiveInt) -> Any:
        """List test suites and hierarchical test-case directories with case counts."""
        return await api.request("GET", f"/projects/{project_id}/sections/hierarchy")

    @mcp.tool
    async def create_test_case_directory(
        test_suite_id: PositiveInt,
        name: Annotated[str, Field(min_length=1, max_length=255)],
        description: str = "",
        parent_section_id: PositiveInt | None = None,
    ) -> Any:
        """Create a test-case directory in a test suite."""
        return await api.request(
            "POST",
            "/sections/",
            json_body={
                "test_suite_id": test_suite_id,
                "name": name,
                "description": description,
                "parent_section_id": parent_section_id,
            },
        )

    @mcp.tool
    async def update_test_case_directory(
        section_id: PositiveInt,
        name: str | None = None,
        description: str | None = None,
        parent_section_id: PositiveInt | None = None,
        order_index: int | None = None,
    ) -> Any:
        """Rename, describe, reorder, or move a test-case directory within its suite."""
        body = {
            key: value
            for key, value in {
                "name": name,
                "description": description,
                "parent_section_id": parent_section_id,
                "order_index": order_index,
            }.items()
            if value is not None
        }
        return await api.request("PUT", f"/sections/{section_id}", json_body=body)

    @mcp.tool
    async def move_test_cases_to_directory(
        test_case_ids: Annotated[list[PositiveInt], Field(min_length=1, max_length=2000)],
        section_id: PositiveInt,
    ) -> Any:
        """Move test cases to a directory in the same test suite."""
        return await api.request(
            "PATCH",
            "/test-cases/bulk",
            json_body={"ids": test_case_ids, "section_id": section_id},
        )

    @mcp.tool
    async def list_mindmaps(project_id: PositiveInt) -> Any:
        """List mind maps in a project."""
        return await api.request("GET", "/test-mindmaps/", params={"project_id": project_id})

    @mcp.tool
    async def get_mindmap(mindmap_id: PositiveInt) -> Any:
        """Get a mind map and its versioned node data."""
        return await api.request("GET", f"/test-mindmaps/{mindmap_id}")

    @mcp.tool
    async def create_mindmap(
        project_id: PositiveInt,
        name: Annotated[str, Field(min_length=1)],
        description: str = "",
        mindmap_data: dict[str, Any] | None = None,
    ) -> Any:
        """Create a mind map with optional versioned node data."""
        data = mindmap_data or {
            "version": 1,
            "rootId": "root",
            "nodes": [{"id": "root", "title": name, "parentId": None}],
        }
        return await api.request(
            "POST",
            "/test-mindmaps/",
            json_body={
                "project_id": project_id,
                "name": name,
                "description": description,
                "mindmap_data": data,
            },
        )

    @mcp.tool
    async def update_mindmap(
        mindmap_id: PositiveInt,
        name: str | None = None,
        description: str | None = None,
        mindmap_data: dict[str, Any] | None = None,
    ) -> Any:
        """Update a mind map's name, description, or node data."""
        body = {
            key: value
            for key, value in {
                "name": name,
                "description": description,
                "mindmap_data": mindmap_data,
            }.items()
            if value is not None
        }
        return await api.request("PUT", f"/test-mindmaps/{mindmap_id}", json_body=body)

    @mcp.tool
    async def list_mindmap_node_test_cases(
        mindmap_id: PositiveInt,
        node_id: Annotated[str, Field(min_length=1)],
    ) -> Any:
        """List test cases linked to a mind-map node."""
        encoded_node_id = quote(node_id, safe="")
        return await api.request("GET", f"/test-mindmaps/{mindmap_id}/nodes/{encoded_node_id}/test-cases")

    @mcp.tool
    async def link_mindmap_node_test_cases(
        mindmap_id: PositiveInt,
        node_id: Annotated[str, Field(min_length=1)],
        test_case_ids: Annotated[list[PositiveInt], Field(min_length=1)],
    ) -> Any:
        """Idempotently link project test cases to a mind-map node."""
        encoded_node_id = quote(node_id, safe="")
        return await api.request(
            "POST",
            f"/test-mindmaps/{mindmap_id}/nodes/{encoded_node_id}/test-cases",
            json_body={"test_case_ids": test_case_ids},
        )

    @mcp.tool
    async def unlink_mindmap_node_test_case(
        mindmap_id: PositiveInt,
        node_id: Annotated[str, Field(min_length=1)],
        test_case_id: PositiveInt,
    ) -> Any:
        """Remove one test-case link from a mind-map node."""
        encoded_node_id = quote(node_id, safe="")
        return await api.request(
            "DELETE",
            f"/test-mindmaps/{mindmap_id}/nodes/{encoded_node_id}/test-cases/{test_case_id}",
        )

    @mcp.tool
    async def list_test_case_mindmaps(test_case_id: PositiveInt) -> Any:
        """List mind maps and nodes linked to a test case."""
        return await api.request("GET", f"/test-cases/{test_case_id}/mindmaps")

    @mcp.tool
    async def preview_openapi_test_cases(
        project_id: PositiveInt,
        document: Annotated[str, Field(min_length=1)],
        filename: Annotated[str, Field(pattern=r"\.(json|yaml|yml)$")] = "openapi.yaml",
    ) -> Any:
        """Parse OpenAPI/Swagger JSON or YAML and preview generated cases without writing data."""
        return await api.request(
            "POST",
            "/import-export/openapi/preview",
            data={"project_id": str(project_id)},
            files={"file": (filename, document.encode("utf-8"), "application/octet-stream")},
        )

    @mcp.tool
    async def commit_openapi_test_cases(
        project_id: PositiveInt,
        test_suite_id: PositiveInt,
        drafts: Annotated[list[dict[str, Any]], Field(min_length=1, max_length=1000)],
        section_id: PositiveInt | None = None,
        duplicate_mode: Annotated[str, Field(pattern=r"^(skip|copy)$")] = "skip",
    ) -> Any:
        """Create reviewed OpenAPI preview drafts in a selected suite and directory."""
        return await api.request(
            "POST",
            "/import-export/openapi/commit",
            json_body={
                "project_id": project_id,
                "test_suite_id": test_suite_id,
                "section_id": section_id,
                "duplicate_mode": duplicate_mode,
                "drafts": drafts,
            },
        )

    return mcp
