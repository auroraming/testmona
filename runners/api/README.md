# TestMona API Runner

The API Runner executes reviewed fixed scripts with relative paths constrained
to the selected environment's `api_url` or `base_url`. It records network steps
and independent status, JSON-path, header, and response-schema assertions. A request completing
successfully is not sufficient for a passed task.

Credentials are stored as encrypted project references. The worker resolves
them with the task lease, injects them in memory, and redacts them from
evidence. Transient 429/502/503/504 responses use bounded exponential backoff.
401 and 403 are not retried. OpenAPI documents can be materialized into this
script shape; the API archives `passed` only when explicit assertions succeed.
Generated requests include safe sample values for required path/query parameters
and required JSON-body fields. Header/cookie credentials and secret-named fields
remain explicit credential references rather than being copied into scripts.
OpenAPI/Swagger JSON response schemas are reduced to a bounded validation
subset (`type`, `required`, `properties`, `items`, `enum`, composition, and
`additionalProperties`). Validation is capped at 20 levels and 500 nodes;
evidence stores match results and error paths rather than response bodies.

Register an `api` Runner, set `TESTMONA_API_RUNNER_TOKEN`, and start it with:

```sh
docker compose --profile api-runner up --build api-runner
```
