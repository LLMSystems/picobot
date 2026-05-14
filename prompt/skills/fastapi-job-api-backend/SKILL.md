---
name: fastapi-job-api-backend
description: Build FastAPI backends that accept requests, queue long-running background work, track job state in SQLite, and expose typed polling APIs. Use this skill when creating or refactoring a FastAPI service for async jobs, subprocess or worker-based execution, job history endpoints, health checks, request validation, rate limiting, and containerized deployment.
metadata:
  author: Max
  stack: fastapi-sqlite-async-jobs
---

# FastAPI Job API Backend

Build backend services that are predictable, typed, and safe to operate. Favor clean request validation, explicit job lifecycles, durable job storage, and separation between the HTTP layer and the background execution layer.

## Workflow

1. Define the API contract first.
   Identify submission endpoints, job lookup endpoints, list endpoints, health checks, request bodies, response bodies, status values, and validation rules before writing service code.

2. Separate HTTP, persistence, and execution concerns.
   Keep routers focused on request handling, services focused on business logic and I/O boundaries, and models focused on typed schemas. Do not blur route code with SQLite details or background-process orchestration.

3. Prefer asynchronous job execution for long-running work.
   If execution may exceed normal HTTP latency expectations, launch a background task, return a job identifier immediately, and expose polling endpoints for status and result retrieval.

4. Persist job state durably.
   Store queued, running, completed, and system-level failure states in SQLite so the API can survive restarts and present history to the frontend.

5. Keep the execution layer decoupled.
   Invoke long-running scripts or worker entrypoints through a dedicated runner service so backend code stays independent from task implementation details.

6. Treat security boundaries explicitly.
   Validate external inputs, avoid storing short-lived secrets in the database, avoid leaking tokens in logs or persisted error fields, and constrain CORS and rate limits deliberately.

7. Design for deployment from the start.
   Keep environment-based configuration explicit, ensure Docker layout is reproducible, and include a simple health endpoint for the target platform.

## Architecture Rules

- Use `main.py` as the app entrypoint.
- Put route handlers under `routers/`.
- Put request and response schemas under `models/`.
- Put storage and runner logic under `services/`.
- Keep database initialization in a dedicated module such as `db.py`.
- Keep environment parsing in `config.py`.
- Keep deployment dependencies explicit through `requirements.txt` and `Dockerfile`.

Prefer a structure like:

```text
api/
  main.py
  routers/
  models/
  services/
  db.py
  config.py
  requirements.txt
  Dockerfile
```

## API Design Rules

- Submission endpoints for long-running work should return `202 Accepted` with a stable job identifier.
- Job detail endpoints should return lifecycle timestamps, current status, result payload when available, and system error details when the backend itself fails.
- Job list endpoints should support reasonable pagination or limits and optional filtering when the UI needs history views.
- Health endpoints should stay cheap and deterministic.
- Keep status semantics narrow and explicit. If the background task itself reports success or failure in its own output, distinguish that from backend-level failures such as crashes, invalid subprocess output, or timeouts.

## Data Modeling Rules

- Use typed request schemas with strict validation for operation names, target references, optional config, and optional authentication tokens.
- Do not persist secrets such as access tokens unless the product truly requires it.
- Store JSON-like `config` and `result` payloads in SQLite as serialized JSON strings if a lightweight design is preferred.
- Persist timestamps in ISO8601 format consistently.
- Keep the job table simple and lifecycle-oriented rather than over-normalized.

## Execution Rules

- A router should validate input, create a queued job record, return immediately, and then launch background execution.
- The background task should update the job to `running`, call the runner service, wait with an explicit timeout budget, parse the output, and then store either `completed` plus result or `system_error` plus backend failure details.
- Keep executable path resolution centralized in the runner service.
- Treat malformed stdout, process crashes, and timeout expiration as backend execution failures rather than user-facing business success states.

## FastAPI Rules

- Use Pydantic models for all external contracts.
- Keep dependency injection simple and readable.
- Use async route handlers and async database access when the service already depends on async execution.
- Keep OpenAPI output clean by using well-named schemas, status codes, and response examples where helpful.

## SQLite Rules

- Use `aiosqlite` for async access.
- Initialize tables at startup or through a dedicated init path.
- Encapsulate CRUD operations in a store/service layer instead of issuing SQL from routers.
- Ensure updates to status, timestamps, result, and error fields are explicit and easy to audit.

## Security Rules

- Accept only trusted input formats and domains relevant to the product.
- Do not write tokens into logs, persisted job records, or returned error payloads.
- Apply rate limiting for submission endpoints.
- Restrict CORS to approved frontend origins.
- Keep demo-friendly access patterns separate from production auth assumptions; if a design intentionally omits auth for job lookup, document that as a deliberate tradeoff.

## Deployment Rules

- Use environment variables for database path, worker base path, and allowed origins.
- Keep Docker images minimal but include required system packages when downstream tasks need them.
- Expose one clear application port and run the service with `uvicorn`.
- Ensure the deployment target can mount or copy sibling worker/task directories in a stable path.

## Output Expectations

Produce:

- a clear FastAPI project layout
- typed request and response models
- a job store with explicit lifecycle updates
- a dedicated execution runner service
- submission, lookup, list, and health routes
- environment-based configuration
- Docker-ready deployment files

Do not produce:

- long-running synchronous request handlers for background jobs
- routers that directly manage raw subprocess orchestration
- token persistence without an explicit requirement
- ambiguous status naming that mixes backend and task-level outcomes
- hidden configuration paths or hard-coded deployment assumptions

## Reference Files

- `references/fastapi-job-server-pattern.md`: Detailed API contract, data model, execution flow, SQLite schema, security rules, dependency list, and deployment pattern for a FastAPI backend that launches external tasks and exposes job polling.
