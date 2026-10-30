# AI automation component evaluation

Status: accepted baseline  
Reviewed: 2026-10-30

This record covers component selection only. A selected component is not
considered integrated until its Runner and end-to-end acceptance are complete.
All third-party executors run outside the main API process and must use the
existing lease, allowlist, assertion, evidence, and audit contracts.

## Current selections

| Capability | Observed version | License | Decision |
| --- | --- | --- | --- |
| Web exploration | `@playwright/mcp` 0.0.83 | Apache-2.0 | Selected and pinned with Playwright/Chromium 1.64.1. Keep the local assertion proxy; MCP tool success is not a test assertion. |
| Web fixed scripts | Playwright 1.64.1 / Chromium 1248 | Apache-2.0 | Selected. Dedicated non-root Web Runner with a 1 GiB default limit. |
| Mobile exploration | `@mobilenext/mobile-mcp` 1.0.14 in the changelog | Apache-2.0 | Conditional selection. Do not use `latest`: the repository package metadata and changelog version currently disagree. Disable telemetry and expose only the approved tool subset. |
| Mobile fixed scripts | Appium 3.8.0 | Apache-2.0 (logger: ISC) | Selected protocol boundary. Android workers need SDK/driver access; iOS workers require macOS/Xcode and cannot be promised on an arbitrary Docker host. |
| API fixed scripts | TestMona native HTTP Runner | Project license | Default. It already shares TestMona's task, assertion, evidence, credential, retry, and audit model. |
| API collection MCP | Bruno MCP, early repository | MIT | Deferred. The official repository has only a small history and executes through the local Bruno CLI while returning full bodies. Re-evaluate after stable tagged releases and a redaction/isolation review. |

Primary evidence: [Playwright MCP package](https://github.com/microsoft/playwright-mcp/blob/main/package.json),
[Playwright MCP guide](https://github.com/microsoft/playwright/blob/main/docs/src/getting-started-mcp.md),
[mobile-mcp changelog](https://github.com/mobile-next/mobile-mcp/blob/main/CHANGELOG.md),
[mobile-mcp package](https://github.com/mobile-next/mobile-mcp/blob/main/package.json),
[mobile-mcp runtime requirements](https://github.com/mobile-next/mobile-mcp),
[Appium package](https://github.com/appium/appium/blob/master/packages/appium/package.json), and
[Bruno MCP](https://github.com/usebruno/bruno-mcp).

## Later specialist Runners

| Component | Observed version/activity | License | Resource and isolation decision |
| --- | --- | --- | --- |
| k6 | 2.3.0 release line | AGPL-3.0 | Suitable for load/performance jobs in a separate CPU/network-limited Runner. Legal review is required before distributing a modified binary. Concurrency, duration, target allowlists, and output size must be capped. |
| OWASP ZAP | 2.17.0 release line | Apache-2.0, with documented third-party notices | Suitable for a separate JVM security Runner. Passive scan may be the first phase; active scan is destructive and requires explicit target approval, authentication isolation, and a higher memory limit. |
| Schemathesis | 4.31.1 release line | MIT | Preferred first schema-fuzzing candidate. Run in a separate Python Runner with request-count, deadline, rate, and destructive-method limits; normalize failures into the existing API result schema. |

Primary evidence: [k6 repository and license](https://github.com/grafana/k6),
[k6 releases](https://github.com/grafana/k6/releases),
[ZAP legal notice](https://github.com/zaproxy/zaproxy/blob/main/LEGALNOTICE.md),
[ZAP 2.17.0 release](https://github.com/zaproxy/zaproxy-website/blob/main/site/content/blog/2025-12-15-zap-2-17-0/index.md),
[Schemathesis repository](https://github.com/schemathesis/schemathesis), and
[Schemathesis releases](https://github.com/schemathesis/schemathesis/releases).

## Rejected shortcuts

- Do not install browsers, Appium, ZAP, k6, or Schemathesis into the main API
  image. They have different trust and resource profiles.
- Do not enable unpinned `npx ...@latest` in production Runners.
- Do not expose arbitrary code execution, app installation/removal, unrestricted
  filesystem access, production targets, or raw credential/body logging through
  MCP tools.
- Do not add both Bruno MCP and another API Agent as defaults while the native
  HTTP Runner already covers deterministic regression.

## Re-evaluation triggers

Review this record before any pinned-version upgrade, when Bruno MCP publishes a
stable release line, when a real mobile device fleet is available, or before a
specialist Runner is shipped. Record the image digest, dependency lock, license
scan, security advisories, measured memory/CPU, and normalized result fixture at
that time.
