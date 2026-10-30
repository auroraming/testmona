"""CI snippets that queue automation work without embedding secrets."""

from __future__ import annotations


def render_ci_templates(project_id: int, runner_type: str) -> dict[str, str]:
    if runner_type not in {"web", "mobile", "api"}:
        raise ValueError("runner_type must be web, mobile, or api")
    body = (
        '{\\"project_id\\":%d,\\"runner_type\\":\\"%s\\",\\"execution_mode\\":\\"script\\",'
        '\\"idempotency_key\\":\\"$TESTMONA_IDEMPOTENCY_KEY\\",'
        '\\"allowlist\\":{\\"origins\\":[\\"https://staging.example.test\\"]},'
        '\\"items\\":[{\\"goal\\":\\"Regression\\",\\"config\\":{\\"credential_refs\\":[\\"ci-account\\"]}}]}'
    ) % (project_id, runner_type)
    curl = f"""curl -fsS -X POST "$TESTMONA_BASE_URL/ai-automation/batches" \\
  -H "Authorization: Bearer $TESTMONA_API_TOKEN" \\
  -H "Content-Type: application/json" \\
  -H "Idempotency-Key: $TESTMONA_IDEMPOTENCY_KEY" \\
  -d "{body}"
# Queuing a batch does not mean the run passed. The API archives passed only when explicit assertions succeed.
"""
    indented = "\n".join(("          " + line) if line else line for line in curl.strip().splitlines())
    workflow = f"""name: TestMona {runner_type} regression
on:
  workflow_dispatch:
jobs:
  queue:
    runs-on: ubuntu-latest
    steps:
      - name: Queue fixed-script batch
        env:
          TESTMONA_BASE_URL: ${{{{ vars.TESTMONA_BASE_URL }}}}
          TESTMONA_API_TOKEN: ${{{{ secrets.TESTMONA_API_TOKEN }}}}
          TESTMONA_IDEMPOTENCY_KEY: ${{{{ github.run_id }}}}-${{{{ github.run_attempt }}}}
        run: |
{indented}
"""
    return {
        "curl": curl,
        "github_actions": workflow,
        "note": "Templates reference TESTMONA_API_TOKEN from the CI secret store. They do not contain a credential value, and a successful HTTP response only means the batch was queued.",
    }
