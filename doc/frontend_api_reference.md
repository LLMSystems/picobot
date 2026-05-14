# Picobot Frontend API Reference

這份文檔給前端整合使用，描述目前 `picobot` 已經實作的 HTTP API 與 SSE 行為。

目前版本已包含：

- `POST /chat`
- `GET /chat/stream`
- `POST /chat/stream`
- `GET /sessions`
- `POST /sessions`
- `PATCH /sessions/{session_id}`
- `GET /sessions/{session_id}/messages`
- `GET /sessions/{session_id}/workspace/tree`
- `GET /sessions/{session_id}/workspace/file`
- `GET /capabilities`
- `DELETE /sessions/{session_id}`
- `GET /health`

---

## 1. Base URL

本機開發預設：

```text
http://127.0.0.1:8000
```

---

## 2. 通用規則

### 2.1 Content-Type

- 一般 JSON API
  - request: `application/json`
  - response: `application/json`
- SSE API
  - response: `text/event-stream`

### 2.2 `session_id`

`session_id` 是前後端共同使用的會話識別碼，用來對應：

- 多輪對話 history
- per-session workspace
- session metadata

### 2.3 `X-Request-Id`

每個 HTTP response 都會帶：

```text
X-Request-Id: req_xxxxx
```

如果是錯誤回應，body 內也會附同一個 `request_id`，方便前後端一起查 log。

### 2.4 錯誤格式

所有 JSON API 都使用同一種錯誤格式：

```json
{
  "error": {
    "code": "MESSAGE_INVALID",
    "message": "message must not be empty",
    "request_id": "req_123456"
  }
}
```

常見 `code`：

- `MESSAGE_INVALID`
- `VALIDATION_ERROR`
- `SESSION_NOT_FOUND`
- `RUNTIME_ERROR`
- `INTERNAL_ERROR`
- `NOT_FOUND`
- `METHOD_NOT_ALLOWED`
- `WORKSPACE_NOT_AVAILABLE`
- `WORKSPACE_PATH_INVALID`
- `WORKSPACE_DIRECTORY_NOT_FOUND`
- `WORKSPACE_NOT_A_DIRECTORY`
- `WORKSPACE_FILE_NOT_FOUND`
- `WORKSPACE_NOT_A_FILE`
- `WORKSPACE_BINARY_FILE_UNSUPPORTED`

---

## 3. 主要資料結構

### 3.1 ChatRequest

```json
{
  "session_id": "demo-session",
  "message": "請幫我讀 README.md"
}
```

### 3.2 ChatStreamRequest

```json
{
  "session_id": "demo-session",
  "message": "請幫我讀 README.md",
  "client_request_id": "frontend-uuid"
}
```

`client_request_id` 目前後端不做核心邏輯使用，但前端可以先保留，未來可用於 cancel / trace。

### 3.3 ChatTraceEvent

`POST /chat` 回傳的 `events` 陣列項目格式：

```json
{
  "event": "tool_call_finished",
  "data": {
    "id": "call_1",
    "name": "read_file",
    "ok": true,
    "result": "1| hello"
  }
}
```

### 3.4 SessionSummary

```json
{
  "session_id": "demo-session",
  "title": "請幫我讀 README.md",
  "created_at": "2026-05-14T10:21:00Z",
  "updated_at": "2026-05-14T10:35:00Z",
  "message_count": 12,
  "last_user_message": "請幫我讀 README.md",
  "last_assistant_preview": "我已經讀完 README.md..."
}
```

說明：

- `title`
  - 若 session 有顯式 title，優先使用
  - 否則 fallback 為第一則 user message 的前 30 字
  - 若連訊息都沒有，預設為 `New Chat`
- `message_count`
  - 只計算 `user` 與 `assistant`
- `last_assistant_preview`
  - 適合 sidebar 顯示

### 3.5 SessionMessage

`GET /sessions/{session_id}/messages` 內的每則 message，至少會有：

```json
{
  "id": "msg_01abc",
  "role": "assistant",
  "content": "hello",
  "created_at": "2026-05-14T10:21:02Z"
}
```

說明：

- `id`
  - 後端持久化時自動補上
  - 可作為前端 message key
- `created_at`
  - 後端持久化時自動補上
  - 可用於排序、時間顯示、未來 regenerate/edit/branch 功能

如果某輪內有 tool calling，history 中也可能包含：

- `assistant` with `tool_calls`
- `tool`

前端如果只是一般聊天畫面，通常只需渲染：

- `role == "user"`
- `role == "assistant"` 且有可見內容的訊息

### 3.6 WorkspaceTreeResponse

```json
{
  "session_id": "s1",
  "path": ".",
  "entries": [
    {
      "path": "doc",
      "name": "doc",
      "type": "directory",
      "size": null,
      "updated_at": "2026-05-14T10:21:00Z"
    },
    {
      "path": "doc/design.md",
      "name": "design.md",
      "type": "file",
      "size": 123,
      "updated_at": "2026-05-14T10:21:00Z"
    }
  ],
  "truncated": false
}
```

### 3.7 WorkspaceFileResponse

```json
{
  "session_id": "s1",
  "path": "doc/design.md",
  "content": "# Design\n\nHello\n",
  "encoding": "utf-8",
  "truncated": false,
  "line_count": 3
}
```

---

## 4. Chat API

## 4.1 `POST /chat`

用途：

- 非串流聊天
- 等整輪 agent loop 完成後，一次回傳完整答案
- 回傳完整 trace events

### Request

```http
POST /chat
Content-Type: application/json
```

```json
{
  "session_id": "demo-session",
  "message": "請幫我讀 README.md"
}
```

### Response 200

```json
{
  "session_id": "demo-session",
  "content": "我已經讀完 README.md，重點如下...",
  "usage": {
    "prompt_tokens": 100,
    "completion_tokens": 30,
    "total_tokens": 130
  },
  "tools_used": ["read_file"],
  "stop_reason": "stop",
  "events": [
    {
      "event": "run_started",
      "data": {
        "session_id": "demo-session",
        "message": "請幫我讀 README.md"
      }
    },
    {
      "event": "tool_call_started",
      "data": {
        "id": "call_1",
        "name": "read_file",
        "arguments": {
          "path": "README.md"
        }
      }
    },
    {
      "event": "tool_call_finished",
      "data": {
        "id": "call_1",
        "name": "read_file",
        "ok": true,
        "result": "# picobot\\n..."
      }
    }
  ]
}
```

### 錯誤

400：

```json
{
  "error": {
    "code": "MESSAGE_INVALID",
    "message": "message must not be empty",
    "request_id": "req_xxx"
  }
}
```

500：

```json
{
  "error": {
    "code": "RUNTIME_ERROR",
    "message": "internal runtime failure",
    "request_id": "req_xxx"
  }
}
```

---

## 4.2 `GET /chat/stream`

用途：

- 使用 SSE 串流 agent 事件與模型輸出
- 適合前端直接用 `EventSource`

### Request

```http
GET /chat/stream?session_id=demo-session&message=請幫我讀README
```

### 特性

- 前端實作簡單
- 可直接使用 `EventSource`
- 缺點是 `message` 放在 query string，不適合長訊息或敏感輸入

---

## 4.3 `POST /chat/stream`

用途：

- 與 `GET /chat/stream` 相同
- 但改用 JSON body 傳送資料
- 適合正式前端整合

### Request

```http
POST /chat/stream
Content-Type: application/json
```

```json
{
  "session_id": "demo-session",
  "message": "請幫我讀 README.md",
  "client_request_id": "frontend-uuid"
}
```

### 前端注意

原生 `EventSource` 不支援 `POST`。  
如果要使用 `POST /chat/stream`，前端需改用：

- `fetch()`
- `ReadableStream`
- 自行解析 SSE frame

建議：

- 簡單頁面：用 `GET /chat/stream`
- 正式產品：用 `POST /chat/stream`

---

## 5. SSE 事件格式

目前串流 endpoint 可能發出以下事件：

1. `run_started`
2. `tool_call_started`
3. `tool_call_finished`
4. `workspace_changed`
5. `delta`
6. `done`
7. `error`

### 5.1 `run_started`

```text
event: run_started
data: {"session_id":"demo-session","message":"請幫我讀 README.md"}
```

### 5.2 `tool_call_started`

```text
event: tool_call_started
data: {"id":"call_1","name":"read_file","arguments":{"path":"README.md"}}
```

### 5.3 `tool_call_finished`

```text
event: tool_call_finished
data: {"id":"call_1","name":"read_file","ok":true,"result":"# picobot\n..."}
```

說明：

- `result` 是完整 tool result
- 可能是字串，也可能是 JSON object

### 5.4 `delta`

```text
event: delta
data: 我
```

### 5.4 `workspace_changed`

```text
event: workspace_changed
data: {"session_id":"s1","paths":["doc/design.md"]}
```

說明：

- agent 成功執行會改動 workspace 的工具後，後端會額外送這個事件
- 目前第一版規則：
  - `write_file` / `edit_file`：回精確 `paths`
  - `exec`：回 `{"paths":[]}`，代表後端無法精確知道哪些檔案變動，前端應將整棵 workspace tree 視為失效

前端建議：

- `paths` 非空時：
  - 只刷新指定檔案
- `paths` 為空陣列時：
  - 重新抓 `workspace/tree`
  - 視需要重抓目前正在預覽的檔案

### 5.5 `delta`

```text
event: delta
data: 我
```

### 5.6 `done`

```text
event: done
data: {"session_id":"demo-session","content":"我已經讀完 README.md","usage":{"prompt_tokens":100,"completion_tokens":30,"total_tokens":130},"tools_used":["read_file"],"stop_reason":"stop"}
```

### 5.7 `error`

```text
event: error
data: {"code":"MESSAGE_INVALID","message":"message must not be empty","request_id":"req_xxx"}
```

---

## 6. Session API

## 6.1 `GET /sessions`

用途：

- 取得 session 清單與 metadata
- 適合 sidebar / 對話列表

### Request

```http
GET /sessions
```

### Response 200

```json
{
  "sessions": [
    {
      "session_id": "demo-session",
      "title": "請幫我讀 README.md",
      "created_at": "2026-05-14T10:21:00Z",
      "updated_at": "2026-05-14T10:35:00Z",
      "message_count": 12,
      "last_user_message": "請幫我讀 README.md",
      "last_assistant_preview": "我已經讀完 README.md..."
    }
  ]
}
```

## 6.2 `POST /sessions`

用途：

- 建立空白 session
- 前端可先建立對話，再導入聊天畫面

### Request

```http
POST /sessions
Content-Type: application/json
```

```json
{
  "title": "Plan next step",
  "session_id": "optional-session-id"
}
```

### Response 200

```json
{
  "session_id": "optional-session-id",
  "title": "Plan next step",
  "created_at": "2026-05-14T10:21:00Z",
  "updated_at": "2026-05-14T10:21:00Z",
  "message_count": 0,
  "last_user_message": "",
  "last_assistant_preview": ""
}
```

說明：

- 若未提供 `session_id`，後端會自動生成 `session_<uuid>`
- 若未提供 `title`，後端會使用 `New Chat`

## 6.3 `PATCH /sessions/{session_id}`

用途：

- 更新 session title

### Request

```http
PATCH /sessions/demo-session
Content-Type: application/json
```

```json
{
  "title": "Renamed session"
}
```

### Response 200

```json
{
  "session_id": "demo-session",
  "title": "Renamed session",
  "created_at": "2026-05-14T10:21:00Z",
  "updated_at": "2026-05-14T10:35:00Z",
  "message_count": 0,
  "last_user_message": "",
  "last_assistant_preview": ""
}
```

### Response 404

```json
{
  "error": {
    "code": "SESSION_NOT_FOUND",
    "message": "Session 'demo-session' not found",
    "request_id": "req_xxx"
  }
}
```

## 6.4 `GET /sessions/{session_id}/messages`

用途：

- 載入某個 session 的完整持久化 history

### Request

```http
GET /sessions/demo-session/messages
```

### Response 200

```json
{
  "session_id": "demo-session",
  "messages": [
    {
      "id": "msg_01abc",
      "role": "user",
      "content": "hello",
      "created_at": "2026-05-14T10:21:01Z"
    },
    {
      "id": "msg_01abd",
      "role": "assistant",
      "content": "hi",
      "created_at": "2026-05-14T10:21:02Z"
    }
  ]
}
```

### 空白 session 行為

如果 session 已存在，但尚未有任何訊息，會回：

```json
{
  "session_id": "demo-session",
  "messages": []
}
```

### Response 404

```json
{
  "error": {
    "code": "SESSION_NOT_FOUND",
    "message": "Session 'demo-session' not found",
    "request_id": "req_xxx"
  }
}
```

## 6.5 `DELETE /sessions/{session_id}`

用途：

- 刪除該 session 的 persisted history

### Request

```http
DELETE /sessions/demo-session
```

### Response 200

```json
{
  "session_id": "demo-session",
  "deleted": true
}
```

注意：

- 目前只刪 session history 與 metadata
- 不會刪 per-session workspace

---

## 7. Workspace API

## 7.1 `GET /sessions/{session_id}/workspace/tree`

用途：

- 列出某個 session workspace 內的目錄內容
- 適合前端 file explorer / sidebar

### Request

```http
GET /sessions/s1/workspace/tree?path=.&recursive=true&max_entries=200
```

Query 參數：

- `path`
  - 相對於 session workspace 的相對路徑
  - 預設為 `.`
- `recursive`
  - 是否遞迴列出
- `max_entries`
  - 最多回傳幾筆

### Response 200

```json
{
  "session_id": "s1",
  "path": ".",
  "entries": [
    {
      "path": "doc",
      "name": "doc",
      "type": "directory",
      "size": null,
      "updated_at": "2026-05-14T10:21:00Z"
    },
    {
      "path": "doc/design.md",
      "name": "design.md",
      "type": "file",
      "size": 123,
      "updated_at": "2026-05-14T10:21:00Z"
    }
  ],
  "truncated": false
}
```

欄位說明：

- `updated_at`
  - 每個檔案/目錄目前的最後修改時間
  - 前端可用於排序、顯示、或局部刷新判斷

### 錯誤

- `SESSION_NOT_FOUND`
- `WORKSPACE_NOT_AVAILABLE`
- `WORKSPACE_PATH_INVALID`
- `WORKSPACE_DIRECTORY_NOT_FOUND`
- `WORKSPACE_NOT_A_DIRECTORY`

## 7.2 `GET /sessions/{session_id}/workspace/file`

用途：

- 讀取某個 session workspace 內的單一 UTF-8 文字檔
- 適合 markdown preview / code preview / document viewer

### Request

```http
GET /sessions/s1/workspace/file?path=doc/design.md&offset=1&limit=2000
```

Query 參數：

- `path`
  - 必填，相對於 session workspace 的檔案路徑
- `offset`
  - 1-indexed 起始行號
- `limit`
  - 最多讀取幾行

### Response 200

```json
{
  "session_id": "s1",
  "path": "doc/design.md",
  "content": "# Design\n\nHello\n",
  "encoding": "utf-8",
  "truncated": false,
  "line_count": 3
}
```

欄位說明：

- `content`
  - 回傳的文字內容
- `encoding`
  - 第一版固定為 `utf-8`
- `truncated`
  - 若因為 `limit` 截斷，會回 `true`
- `line_count`
  - 檔案總行數

### 錯誤

- `SESSION_NOT_FOUND`
- `WORKSPACE_NOT_AVAILABLE`
- `WORKSPACE_PATH_INVALID`
- `WORKSPACE_FILE_NOT_FOUND`
- `WORKSPACE_NOT_A_FILE`
- `WORKSPACE_BINARY_FILE_UNSUPPORTED`

### 前端建議

當 `/chat/stream` 或 `POST /chat` 的 tool event 顯示 agent 使用：

- `write_file`
- `edit_file`
- `exec`

前端可以直接根據工具參數中的 `path` 重新呼叫：

- `GET /sessions/{session_id}/workspace/file`

這樣就能在 agent 生成完文件後，立刻刷新右側預覽面板。

更推薦的做法是直接使用：

- `workspace_changed`

策略如下：

1. 若 `paths` 有內容：
   - 只刷新那些檔案
2. 若 `paths` 是空陣列：
   - 代表整棵 workspace tree 失效
   - 前端應重新抓 `GET /sessions/{session_id}/workspace/tree`

---

## 8. Capabilities API

## 8.1 `GET /capabilities`

用途：

- 前端初始化時取得目前 agent 能力摘要
- 用來渲染 tools、feature flags、與 model 標示

### Request

```http
GET /capabilities
```

### Response 200

```json
{
  "model": {
    "provider": "openai_compat",
    "name": "gpt-4.1-mini"
  },
  "max_iterations": 8,
  "tools": [
    {
      "name": "exec",
      "description": "Execute a shell command and return its output. Use this for tests, build, lint, or runtime verification. Output is truncated at 10,000 chars.",
      "category": "shell",
      "dangerous": true
    },
    {
      "name": "read_file",
      "description": "Read UTF-8 text files with optional line pagination. Text format: LINE_NUM| CONTENT. Use offset and limit for large files. Reads exceeding ~128K chars are truncated.",
      "category": "filesystem",
      "dangerous": false
    }
  ],
  "features": {
    "streaming": true,
    "session_workspace": true,
    "file_upload": false,
    "multimodal": false
  }
}
```

欄位說明：

- `model`
  - 顯示目前 provider 與 model 名稱
- `max_iterations`
  - agent loop 上限
- `tools`
  - 前端可拿來顯示 tool list / icon / badge
- `features.streaming`
  - 是否支援 SSE chat streaming
- `features.session_workspace`
  - 是否啟用 per-session workspace
- `features.file_upload`
  - 目前固定為 `false`
- `features.multimodal`
  - 目前固定為 `false`

---

## 9. 其他 API

## 9.1 `GET /health`

用途：

- 健康檢查

### Response 200

```json
{
  "status": "ok"
}
```

---

## 10. 前端整合建議

### 10.1 一般聊天頁

建議流程：

1. 頁面載入時呼叫 `GET /sessions`
2. 點某個 session 時呼叫 `GET /sessions/{session_id}/messages`
3. 送新訊息時優先使用 `POST /chat/stream` 或 `GET /chat/stream`
4. 如果頁面不需要即時體驗，可退回 `POST /chat`

### 10.2 Sidebar

直接使用 `GET /sessions`：

- `title`
- `updated_at`
- `last_assistant_preview`

### 10.3 Workspace Preview

如果你要做「agent 生成文檔後立即可見」的 UI，建議流程：

1. 前端接 `/chat/stream` 或 `POST /chat` 的 `events`
2. 看到 `write_file` / `edit_file` 完成
3. 取出工具參數中的 `path`
4. 呼叫 `GET /sessions/{session_id}/workspace/file`
5. 更新右側 markdown / code preview

### 10.4 Message Key

前端渲染 message list 時，建議優先使用：

1. `message.id`
2. 若舊資料沒有 `id`，再 fallback 到 index

### 10.5 Tool Event UI

如果是 agent UI，建議顯示：

- `run_started`
- `tool_call_started`
- `tool_call_finished`
- `workspace_changed`
- `delta`
- `done`
- `error`

其中 `tool_call_finished.data.result` 已經是完整結果，前端可選擇：

- 直接顯示全文
- 預設折疊，展開看詳情

---

## 11. JavaScript 範例

## 11.1 `POST /chat`

```js
async function sendChat(sessionId, message) {
  const response = await fetch("http://127.0.0.1:8000/chat", {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      session_id: sessionId,
      message
    })
  });

  const payload = await response.json();

  if (!response.ok) {
    throw new Error(payload.error?.message || "Request failed");
  }

  return payload;
}
```

## 11.2 `GET /chat/stream` with EventSource

```js
function openChatStream(sessionId, message, handlers) {
  const url = new URL("http://127.0.0.1:8000/chat/stream");
  url.searchParams.set("session_id", sessionId);
  url.searchParams.set("message", message);

  const es = new EventSource(url.toString());

  es.addEventListener("run_started", (event) => {
    handlers.onRunStarted?.(JSON.parse(event.data));
  });

  es.addEventListener("tool_call_started", (event) => {
    handlers.onToolStarted?.(JSON.parse(event.data));
  });

  es.addEventListener("tool_call_finished", (event) => {
    handlers.onToolFinished?.(JSON.parse(event.data));
  });

  es.addEventListener("delta", (event) => {
    handlers.onDelta?.(event.data);
  });

  es.addEventListener("done", (event) => {
    handlers.onDone?.(JSON.parse(event.data));
    es.close();
  });

  es.addEventListener("error", (event) => {
    handlers.onError?.(event);
    es.close();
  });

  return es;
}
```

---

## 12. 已知限制

目前仍有幾個重要限制：

1. `GET /chat/stream` 仍把 `message` 放在 query string
2. 目前尚未有 auth / permission control / rate limit
3. `DELETE /sessions/{session_id}` 不會刪 workspace
4. `POST /chat/stream` 需要前端自行處理 `fetch + ReadableStream + SSE parsing`
5. 目前還沒有 abort / cancel API
6. workspace API 第一版是 read-only，不提供前端直接改檔

---

## 13. 總結

目前這套前端 API 已經足夠支撐一個正常的 chatbot / agent UI：

- 非串流聊天：`POST /chat`
- 串流聊天：`GET /chat/stream` / `POST /chat/stream`
- session 列表：`GET /sessions`
- session 建立與改名：`POST /sessions` / `PATCH /sessions/{session_id}`
- message 歷史：`GET /sessions/{session_id}/messages`
- workspace 瀏覽與檔案預覽：`GET /sessions/{session_id}/workspace/tree` / `GET /sessions/{session_id}/workspace/file`
- 能力摘要：`GET /capabilities`
- session 刪除：`DELETE /sessions/{session_id}`
- 健康檢查：`GET /health`

目前前端已經可以安全依賴：

- session metadata
- message `id`
- message `created_at`
- create / rename session
- empty session history 查詢
- per-session workspace tree
- per-session workspace file preview
