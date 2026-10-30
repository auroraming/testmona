# AI automation architecture baseline

Status: orchestration, evidence, and the Web AI assertion lifecycle are implemented. Real-browser acceptance is still open, and no Runner is enabled by default.

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

The Agent Runtime now has a hardened Playwright MCP stdio transport boundary:
the package reference must be an exact version, the browser is headless and
isolated, the target origin is explicit, service workers are blocked, and the
allowlist excludes arbitrary JavaScript execution, unrestricted code, and file
upload tools.

Web AI tasks connect that transport to an assertion proxy and a per-task
process lifecycle. The proxy adds `browser_assert_text`,
`browser_assert_visible`, `browser_assert_url`, and `browser_assert_network`.
Text assertions match a whole phrase. Those tools read a snapshot, tab list,
or captured request list and return `passed: true` only when the observation
matches. Direct navigation outside the environment origin is rejected before
it reaches the browser. After navigation or a click, the proxy also checks the
resulting page URL, because the MCP `--allowed-origins` flag does not stop
redirects. Request-detail and image payloads are hidden. Automatic MCP files
go to a temporary output directory that is removed with the process, not the
workspace. The container runs the local `@playwright/mcp@0.0.83` CLI on
playwright-core 1.64.1 so it uses Chromium revision 1248 from the Playwright
image; it does not use `npx` or `--browser=chrome`. The stdio client speaks
newline-delimited JSON, which is the framing that package reads. Before the
MCP process stops, the Web Runner uploads screenshot, Trace, and console-log
files and stores their artifact references on the evidence rows. A terminal
report also writes the linked test result, execution record, and test-run
status. Model calls use the lease-scoped completion endpoint. An expired lease cannot complete,
renew, or report a pass. Batch regression, CI templates, and a real-browser
end-to-end run are still open. The Node Web Runner is the production
executor; the Python helper follows the same origin and assertion rules.

## API Runner baseline

The optional `api-runner` Compose profile uses the same lease, heartbeat,
evidence, and report protocol. Fixed scripts issue requests only to relative
paths under the configured environment origin and record network observations
plus independent status, JSON-path, and header assertions. A successful HTTP
round trip never passes a task without assertions. Credential references are
encrypted at rest and resolved only for the active lease; evidence and audit
records store the reference name. Transient statuses retry with capped
backoff, while 401 and 403 do not. OpenAPI documents can be turned into this
script shape. Native runner output and an API MCP observation both normalize
to `testmona.api_result.v1`. A live API MCP server has not been compared.

## Mobile Runner baseline

The optional `mobile-runner` profile is a small W3C WebDriver client that
connects to an externally managed Appium 2 endpoint. It probes the endpoint and
creates one exclusive session before executing tap, type, swipe, screenshot,
text-assertion, or visibility-assertion steps. Missing Appium or unavailable
devices produce a blocked task rather than a false pass. Android emulators and
iOS/macOS/Xcode remain deployment responsibilities of the device host; a
server-side device catalog now records capabilities, explicit locks, and
offline reclaim. mobile-mcp discovery exposes an allowlist contract only.
Android and iOS end-to-end runs still require real devices and are not claimed.

## Artifact boundary

An active Runner with both its identity token and task lease may upload PNG,
ZIP, JSON, or plain-text evidence up to 20 MB. The backend assigns a random
name, records size and SHA-256, and returns an opaque relative reference. A user
may download the file only when they can read the project and an immutable
evidence row on that task references it. Web scripts now upload screenshots and
Playwright traces; Mobile scripts upload screenshots without embedding base64
data in evidence payloads.

## Platform controls added after the runner baseline

Fixed Web scripts also emit sanitized network evidence: method, redacted URL,
status, and resource type. Bodies, cookies, and authorization headers are not
stored. Sequence numbers at 700000 and above keep network rows from colliding
with step and trace evidence. Batch creation is idempotent per project key.
CI templates interpolate `TESTMONA_API_TOKEN` from the runner environment and
do not embed a secret. The API archives a runner `passed` report as `failed`
unless explicit assertion records passed. An expired lease at the default
attempt limit marks the same task `timed_out` instead of starting another
execution record. Token alerts fire at 80% and at the budget; estimated cost
stays null until a provider price exists. Script drafts record source,
revision, environment, and approver, and approval does not enqueue a run.
Production environment types and payment-like hosts stay denied. Docker
end-to-end browser, device, and live MCP acceptance are still open.

Failure suggestions are derived from assertion, network, log, and screenshot
references. Confirming one records an audit entry and does not create a defect.
Exploration evidence can be saved as another script draft, and rollback copies
an older revision into a new draft without executing it. Terminal reports append
one token ledger row with input, provider-reported cached, and output counts.
`estimated_cost_micros` stays null. A runner defaults to one active lease;
`capabilities.max_concurrent` can raise that cap to 20. An expired cancellation
lease is finalized as cancelled on the same task. OpenAPI preview accepts pasted
text, resolves local JSON pointers with a depth and cycle limit, and can emit
success-only, required-field, or constraint-boundary drafts. Remote references
stay rejected.
