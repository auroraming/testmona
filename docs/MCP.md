# TestMona MCP Server

TestMona includes a local stdio MCP server that exposes test-case directories,
mind-map links, and OpenAPI-to-test-case conversion to MCP clients. The MCP
server calls the normal TestMona HTTP API, so project permissions, viewer
read-only rules, validation, and audit behavior remain in force.

## Prerequisites

1. Start the TestMona backend.
2. In TestMona, open **API tokens** and create a personal token.
3. Add the server to your MCP client. Replace the repository path and token:

```json
{
  "mcpServers": {
    "testmona": {
      "command": "/absolute/path/to/testmona/backend/venv/bin/python",
      "args": ["/absolute/path/to/testmona/backend/mcp_server.py"],
      "env": {
        "TESTMONA_URL": "http://127.0.0.1:8000",
        "TESTMONA_API_TOKEN": "tmona_replace_with_your_token"
      }
    }
  }
}
```

Treat the token like a password. Do not commit a real token to the repository.

## Available tools

### Language

- `get_default_language`
- `set_default_language` (administrator token required)

### Test-case directories

- `list_test_case_directories`
- `create_test_case_directory`
- `update_test_case_directory`
- `move_test_cases_to_directory`

### Mind maps

- `list_mindmaps`
- `get_mindmap`
- `create_mindmap`
- `update_mindmap`
- `list_mindmap_node_test_cases`
- `link_mindmap_node_test_cases`
- `unlink_mindmap_node_test_case`
- `list_test_case_mindmaps`

### OpenAPI conversion

- `preview_openapi_test_cases` parses OpenAPI 3.x JSON/YAML text without writing data.
- `commit_openapi_test_cases` writes only reviewed drafts to a selected suite and optional directory.

The preview and commit steps are intentionally separate so an MCP client can
show generated test cases for human review before creating records.

## Environment variables

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `TESTMONA_API_TOKEN` | Yes | — | Personal `tmona_...` Bearer token |
| `TESTMONA_URL` | No | `http://127.0.0.1:8000` | TestMona backend base URL |

## Troubleshooting

- `TESTMONA_API_TOKEN is required`: configure the token in the MCP client's server environment.
- HTTP 401: the token is invalid or revoked.
- HTTP 403: the token owner lacks the required project permission, or is a read-only viewer attempting a write.
- Connection failure: verify the backend is running and `TESTMONA_URL` is reachable from the MCP client.
