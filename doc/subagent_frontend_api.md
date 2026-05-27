# Subagent Frontend API

This document describes the backend APIs that support:

- subagent reload recovery
- persisted subagent timelines
- live subagent updates over SSE

These APIs are session-scoped.


## Recommended Frontend Flow

For a session page:

1. load persisted subagent summaries
2. load persisted timeline events for the subagent the user wants to inspect
3. open the session SSE stream
4. merge incoming live events by `task_id + seq`

Recommended order:

1. `GET /sessions/{session_id}/subagents`
2. `GET /sessions/{session_id}/subagents/{task_id}/events`
3. `GET /sessions/{session_id}/events/stream`


## Base Concepts

### Session

All subagent data is scoped to a main-agent session.

### Subagent Run

A persisted summary row for one subagent task.

### Subagent Event

A persisted or live timeline event for one subagent task.


## 1. List Subagents

`GET /sessions/{session_id}/subagents`

Returns persisted subagent runs for one session.

### Query Parameters

- `phase` (optional)
- `limit` (optional, default `100`)

### Example

`GET /sessions/s1/subagents`

### Response

```json
{
  "session_id": "s1",
  "items": [
    {
      "task_id": "sub_1",
      "parent_session_id": "s1",
      "label": "collect refs",
      "task": "Collect references",
      "workspace": "D:/tmp/sub_1",
      "phase": "done",
      "started_at": "2026-05-27T12:00:00Z",
      "finished_at": "2026-05-27T12:00:10Z",
      "stop_reason": "stop",
      "ok": true,
      "error": null,
      "usage": {
        "prompt_tokens": 10
      },
      "tool_events": [],
      "final_content": "done"
    }
  ]
}
```

### Notes

- use this for reload recovery
- use `phase` to filter running or completed tasks
- `tool_events` here is summary-level data, not the full timeline


## 2. Get One Subagent Run

`GET /sessions/{session_id}/subagents/{task_id}`

Returns one persisted subagent summary.

### Example

`GET /sessions/s1/subagents/sub_1`

### Response

```json
{
  "task_id": "sub_1",
  "parent_session_id": "s1",
  "label": "collect refs",
  "task": "Collect references",
  "workspace": "D:/tmp/sub_1",
  "phase": "running",
  "started_at": "2026-05-27T12:00:00Z",
  "finished_at": null,
  "stop_reason": null,
  "ok": null,
  "error": null,
  "usage": {},
  "tool_events": [],
  "final_content": null
}
```

### Notes

- use this when the UI needs a single task card or detail header
- if the task does not belong to the session, the API returns `404`


## 3. Get Subagent Timeline Events

`GET /sessions/{session_id}/subagents/{task_id}/events`

Returns persisted timeline events for one subagent.

### Query Parameters

- `after_seq` (optional)
- `limit` (optional, default `500`)

### Example

`GET /sessions/s1/subagents/sub_1/events`

### Response

```json
{
  "session_id": "s1",
  "task_id": "sub_1",
  "events": [
    {
      "id": 1,
      "task_id": "sub_1",
      "parent_session_id": "s1",
      "seq": 1,
      "event_type": "subagent_spawned",
      "created_at": "2026-05-27T12:00:00Z",
      "payload": {
        "label": "collect refs",
        "data": {
          "task": "Collect references"
        }
      }
    },
    {
      "id": 2,
      "task_id": "sub_1",
      "parent_session_id": "s1",
      "seq": 2,
      "event_type": "subagent_delta",
      "created_at": "2026-05-27T12:00:01Z",
      "payload": {
        "label": "collect refs",
        "data": {
          "delta": "Scanning files..."
        }
      }
    }
  ]
}
```

### Notes

- this is the main reload-recovery API for subagent progress
- `seq` is monotonic per `task_id`
- frontend should sort by `seq`
- `after_seq` can be used later for incremental fetches if needed


## 4. Live Session Event Stream

`GET /sessions/{session_id}/events/stream`

Returns a Server-Sent Events stream for live background session events.

Right now this is mainly used for subagent live updates.

### Content Type

`text/event-stream`

### Example

```ts
const es = new EventSource(`/sessions/${sessionId}/events/stream`)

es.addEventListener('subagent_delta', (ev) => {
  const payload = JSON.parse((ev as MessageEvent).data)
  console.log(payload)
})
```

### SSE Frame Example

```text
event: subagent_delta
data: {"session_id":"s1","task_id":"sub_1","label":"collect refs","event":"subagent_delta","data":{"delta":"Scanning files..."},"seq":2,"created_at":"2026-05-27T12:00:01Z"}
```

### Parsed Event Payload

```json
{
  "session_id": "s1",
  "task_id": "sub_1",
  "label": "collect refs",
  "event": "subagent_delta",
  "data": {
    "delta": "Scanning files..."
  },
  "seq": 2,
  "created_at": "2026-05-27T12:00:01Z"
}
```

### Notes

- this stream is for live events only
- it does not replay history by itself
- always hydrate from the persisted APIs first, then connect SSE


## Event Types

Currently supported subagent event names:

- `subagent_spawned`
- `subagent_phase_changed`
- `subagent_delta`
- `subagent_tool_call_started`
- `subagent_tool_call_finished`
- `subagent_iteration_completed`
- `subagent_completed`
- `subagent_failed`
- `subagent_cancelled`


## Event Payload Shapes

All live SSE events share this outer shape:

```json
{
  "session_id": "s1",
  "task_id": "sub_1",
  "label": "collect refs",
  "event": "subagent_delta",
  "data": {},
  "seq": 2,
  "created_at": "2026-05-27T12:00:01Z"
}
```

### `subagent_spawned`

```json
{
  "task_id": "sub_1",
  "label": "collect refs",
  "task": "Collect references",
  "workspace": "D:/tmp/sub_1"
}
```

### `subagent_phase_changed`

```json
{
  "phase": "running"
}
```

or terminal:

```json
{
  "phase": "done",
  "stop_reason": "completed",
  "ok": true
}
```

### `subagent_delta`

```json
{
  "delta": "Scanning files..."
}
```

### `subagent_tool_call_started`

```json
{
  "id": "tc1",
  "name": "glob",
  "arguments": {
    "path": "."
  }
}
```

### `subagent_tool_call_finished`

```json
{
  "id": "tc1",
  "name": "glob",
  "ok": true,
  "result": ["a.py"]
}
```

### `subagent_iteration_completed`

```json
{
  "iteration": 1,
  "usage": {
    "prompt_tokens": 3
  }
}
```

### `subagent_completed`

```json
{
  "ok": true,
  "stop_reason": "completed",
  "content": "Finished the task",
  "error": null,
  "usage": {
    "prompt_tokens": 3
  }
}
```

### `subagent_failed`

```json
{
  "ok": false,
  "stop_reason": "error",
  "content": "Error: ...",
  "error": "..."
}
```

### `subagent_cancelled`

```json
{
  "ok": false,
  "stop_reason": "cancelled",
  "content": "Cancelled"
}
```


## Suggested Frontend State Model

Recommended state structure:

```ts
type SubagentSummary = {
  task_id: string
  label: string
  phase: string
  started_at: string
  finished_at: string | null
  final_content: string | null
}

type SubagentTimelineEvent = {
  task_id: string
  seq: number
  event_type: string
  created_at: string
  payload: Record<string, unknown>
}
```

Recommended flow:

1. fetch subagent summaries
2. choose a task
3. fetch persisted events
4. connect SSE
5. merge incoming live events by `task_id + seq`
6. ignore duplicates


## Error Codes

Possible errors:

- `SESSION_NOT_FOUND`
- `SUBAGENT_NOT_FOUND`

Example:

```json
{
  "error": {
    "code": "SUBAGENT_NOT_FOUND",
    "message": "Subagent 'missing' not found in session 's1'",
    "request_id": "req_abc123"
  }
}
```


## Minimal Integration Plan

For reload recovery plus live updates:

1. call `GET /sessions/{session_id}/subagents`
2. call `GET /sessions/{session_id}/subagents/{task_id}/events`
3. open `GET /sessions/{session_id}/events/stream`
4. merge new events into the same in-memory timeline

This is the intended usage pattern for the current backend.
