# TestMona Web Runner

This optional worker executes reviewed, fixed Web scripts outside the main API
process. It uses Playwright and Chromium `1.64.1`; the package and official
container image versions are deliberately identical.

## Start

1. Register a `web` Runner in TestMona and copy the one-time `tmr_...` token.
2. Set `TESTMONA_WEB_RUNNER_TOKEN` in the deployment environment.
3. Run `docker compose --profile web-runner up --build web-runner`.

Do not put the token in source control. The worker drops Linux capabilities,
runs as the image's `pwuser`, and only reaches TestMona through the private
Runner protocol.

## Fixed script format

Create a Web automation task with `execution_mode: "script"` and a `config.script`
array. Supported actions are `navigate`, `click`, `fill`, `assert_text`,
`assert_visible`, and `screenshot`. Selectors and values are explicit. At least
one assertion must pass before the task can pass; successful navigation or
clicks alone never count as a passed test.

Screenshots and the Playwright Trace are uploaded through the lease-protected
artifact endpoint and attached to immutable evidence. Temporary local files are
removed after upload.

## AI exploration

Create a Web task with `execution_mode: "ai"` and an environment whose
`app_url` or `base_url` is an origin, for example `https://example.test`.
The worker starts the installed `@playwright/mcp@0.0.83` CLI. npm overrides
force `playwright` and `playwright-core` to `1.64.1`, which is Chromium
revision 1248, the same browser shipped in
`mcr.microsoft.com/playwright:v1.64.1-noble`. The process is not launched
with `npx` or `--browser=chrome`, because those would select a different
browser than the image. It runs headless and isolated, writes automatic
screenshots outside the workspace, and stops when the task finishes, fails,
or is cancelled.

Text assertions match a whole phrase, so a single letter inside another word
does not pass. The MCP allowed-origins flag is not treated as a security
boundary: direct external navigation is rejected before the browser sees it,
and a same-origin URL that redirects, or a click that leaves the origin, is
rejected after the resulting page URL is checked. `@playwright/mcp@latest`
and origins that include a path are rejected when the task or environment is
saved. Real-browser end-to-end acceptance, batch regression, and CI templates
are still open.
