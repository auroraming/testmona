# TestMona API Runner

The API Runner executes reviewed fixed scripts with relative paths constrained
to the selected environment's `api_url` or `base_url`. It records network steps
and independent status, JSON-path, and header assertions. A request completing
successfully is not sufficient for a passed task.

Credentials are stored as encrypted project references. The worker resolves
them with the task lease, injects them in memory, and redacts them from
evidence. Transient 429/502/503/504 responses use bounded exponential backoff.
401 and 403 are not retried. OpenAPI documents can be materialized into this
script shape; the API archives `passed` only when explicit assertions succeed.

Register an `api` Runner, set `TESTMONA_API_RUNNER_TOKEN`, and start it with:

```sh
docker compose --profile api-runner up --build api-runner
```
