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

## Internal MCP client contract

The Agent Runtime uses `AutomationMCPClient` instead of constructing raw MCP
requests. Every task supplies a non-empty tool allowlist. Discovery hides all
other server tools, arguments are checked against the discovered JSON Schema
before transport, and ping/call timeouts and protocol failures become stable,
structured errors. This client is an internal execution dependency and is
separate from TestMona's user-facing remote `/mcp` server.

## Agent Runtime contract

`AutomationAgentRuntime` asks the configured AI Manager for one JSON decision at
a time, then invokes only tools exposed by the restricted MCP client. It checks
cancellation before each decision, caps steps, wall-clock time, and total token
usage, and returns stable error codes for malformed model output, MCP failures,
timeouts, and exhausted budgets. A tool call is recorded as an observation; it
does not itself make the task pass, and the prompt requires explicit assertion
results before a successful summary. Persistence into the task/evidence models
is connected through a small asynchronous Runner protocol client. A claimed
lease includes a snapshot of the linked test case, structured steps, and an
allowlisted subset of environment metadata; arbitrary environment credentials
and step data are excluded. The SDK maintains heartbeats, appends immutable
step observations through the Runtime callback, and reports terminal status and
token totals idempotently. Production Web/Mobile/API tool implementations remain
the next deployment boundary.

## Web Runner baseline

The optional `web-runner` Compose profile is isolated from the API image and
pins both the Playwright package and official Chromium image to `1.64.1`. Its
first fixed-script executor supports navigation, click, fill, screenshot, text
assertions, and visibility assertions, with heartbeat cancellation and evidence
after each step. It refuses to pass a script with no explicit assertion. AI
exploration through Playwright MCP and controlled screenshot/Trace upload remain
open before this Runner is production-ready.

## API Runner baseline

The optional `api-runner` Compose profile uses the same lease, heartbeat,
evidence, and report protocol. Fixed scripts issue requests only to relative
paths under the configured environment origin and record network observations
plus independent status, JSON-path, and header assertions. A successful HTTP
round trip never passes a task without assertions. Credential-reference
injection, retries, OpenAPI script materialization, and the API MCP comparison
remain open.

## Mobile Runner baseline

The optional `mobile-runner` profile is a small W3C WebDriver client that
connects to an externally managed Appium 2 endpoint. It probes the endpoint and
creates one exclusive session before executing tap, type, swipe, screenshot,
text-assertion, or visibility-assertion steps. Missing Appium or unavailable
devices produce a blocked task rather than a false pass. Android emulators and
iOS/macOS/Xcode remain deployment responsibilities of the device host; a
server-side device catalog/lock and mobile-mcp discovery are still open.
