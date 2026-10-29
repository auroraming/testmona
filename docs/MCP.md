# TestMona Remote MCP

TestMona exposes a FastMCP Streamable HTTP endpoint at:

```text
https://your-testmona-host/mcp
```

It uses the same personal API tokens as the REST API. MCP tools re-enter the
normal TestMona API in-process, so project permissions, viewer read-only rules,
validation, and audit behavior remain in force. There is no stdio server.

## Connect a client

1. Start or deploy the TestMona backend.
2. In TestMona, open **API tokens** and create a personal token.
3. Add the remote URL to an MCP client and send the token as a Bearer token.

Generic configuration:

```json
{
  "mcpServers": {
    "testmona": {
      "url": "https://your-testmona-host/mcp",
      "headers": {
        "Authorization": "Bearer tmona_replace_with_your_token"
      }
    }
  }
}
```

Clients with a dedicated API-token field can use the same URL and paste only
the `tmona_...` value into that field. Do not put tokens in the URL query string
and do not commit a real token to the repository.

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

- `preview_openapi_test_cases` parses OpenAPI/Swagger JSON or YAML without writing data.
- `commit_openapi_test_cases` writes reviewed drafts to a selected suite and optional directory.

Preview and commit are intentionally separate so a client can show generated
test cases for human review before creating records.

## Sharing with other users

Deploy TestMona on an HTTPS address reachable by those users. Each user creates
their own personal API token and configures the same `/mcp` URL. Never share one
token across users: permissions and audit identity come from the token owner.

## Troubleshooting

- HTTP 401: the token is missing, invalid, expired, revoked, or belongs to a disabled user.
- HTTP 403: the token owner lacks the project permission or is a read-only viewer attempting a write.
- HTTP 404: confirm the URL ends in `/mcp` and the deployed backend includes the FastMCP dependency.
- Connection failure: confirm the HTTPS endpoint is reachable from the MCP client.
