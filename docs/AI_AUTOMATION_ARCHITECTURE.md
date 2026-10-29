# AI automation architecture baseline

Status: orchestration and evidence baseline implemented; no production Runner is enabled yet.

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

Authenticated MCP clients can create, list, inspect, and cancel tasks and read
their evidence through the same REST/RBAC boundary. The internal Runner protocol
is intentionally excluded from MCP so a personal user token cannot impersonate
a worker. User actions and terminal Runner reports are written to the existing
project audit feed; Runner events retain explicit Runner identity metadata and
are attributed to the user who requested the task.

## Security invariants

- Task operations are checked against project read/execute permissions.
- Linked cases, runs, and environments must belong to the same project.
- Inline API keys, authorization headers, passwords, secrets, and tokens are
  rejected. Payloads carry credential references only.
- Queued tasks cancel immediately; active tasks enter `cancel_requested` until
  a Runner acknowledges cancellation.
- Runner callbacks use expiring leases, and repeated equivalent terminal reports
  are idempotent. Step evidence and audit events are persisted before any
  production Runner is enabled.

## Evidence contract

Active runners append immutable evidence with a task-local sequence number.
Supported types are step, assertion, log, screenshot, trace, and network.
Retries with the same sequence and content are idempotent; conflicting content
is rejected. Binary files remain in controlled object storage and evidence only
stores a relative storage reference. External URLs, filesystem paths, oversized
payloads, and credential-shaped fields are rejected.
