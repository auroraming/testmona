# TestMona API Runner

The API Runner executes reviewed fixed scripts with relative paths constrained
to the selected environment's `api_url` or `base_url`. It records network steps
and independent status, JSON-path, and header assertions. A request completing
successfully is not sufficient for a passed task.

Register an `api` Runner, set `TESTMONA_API_RUNNER_TOKEN`, and start it with:

```sh
docker compose --profile api-runner up --build api-runner
```
