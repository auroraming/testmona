# AI automation architecture baseline

Status: first implementation slice; no Runner dispatch is enabled yet.

## Reuse decisions

- AI Provider configuration, encrypted credentials, routing, fallback, timeout,
  usage counters, and token limits remain in `services/ai_manager.py`.
- `/mcp` remains the remote integration surface. An internal Agent Runtime will
  use an MCP client; it must not bypass REST/RBAC or store server credentials in
  task payloads.
- Existing `TestRun`, `TestExecution`, and `TestResult` remain the source of
  finalized manual/fixed-script outcomes. AI orchestration tasks link to them
  instead of replacing them.
- Existing OpenAPI/Swagger preview and commit remain the API test-generation
  entry point.

## New boundary

`AIAutomationTask` is the project-scoped orchestration record shared by Web,
Mobile, and API execution. It stores runner type, mode, lifecycle, budgets,
safe configuration, token totals, result summary, and links to a test case,
test run, and environment.

The first slice exposes create/list/read/cancel endpoints. Administrators can
register project-scoped runners; the one-time token is stored only as a hash and
can be rotated or revoked. Workers claim matching queued tasks using a short
lease, renew it through heartbeats, observe cancellation requests, and report a
terminal result idempotently. Creating a task only queues durable intent and
never marks a test as passed; independent assertions still determine outcomes.

## Security invariants

- Task operations are checked against project read/execute permissions.
- Linked cases, runs, and environments must belong to the same project.
- Inline API keys, authorization headers, passwords, secrets, and tokens are
  rejected. Payloads carry credential references only.
- Queued tasks cancel immediately; active tasks enter `cancel_requested` until
  a Runner acknowledges cancellation.
- Runner callbacks use expiring leases, and repeated equivalent terminal reports
  are idempotent. Step evidence storage and audit events remain required before
  a production Runner is enabled.
