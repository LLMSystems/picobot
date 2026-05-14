# Picobot FastAPI Chat API 設計文檔

## 1. 目標

建立一個適合一般聊天機器人產品使用的 Web Chat 後端。

目前的優先目標：

1. `POST /chat`：回傳單次完整回答
2. `GET /chat/stream`：使用 SSE 進行流式回覆
3. 以 `AioSQLiteSessionStore` 作為預設的持久化 session store

這份文檔除了描述目前已實作的 API，也整理了後續若要做成一個正常 chatbot 後端，還需要哪些 API。


## 2. 目前 V1 範圍

已包含：

- 非同步 FastAPI handler
- 以 session 為基礎的多輪對話
- 非流式 chat API
- SSE 流式 chat API
- 透過 `AioSQLiteSessionStore` 持久化保存對話紀錄

目前不包含：

- 身份驗證
- rate limiting
- 使用者 / 帳號模型
- feedback / analytics
- 檔案上傳
- 對話標題與 metadata 管理


## 3. 高層架構

```text
Browser Chat UI
  -> FastAPI endpoint
    -> LocalAgentRuntime (async path)
      -> AgentLoop.run_async / run_stream_async
        -> Provider.generate_async / stream_generate_async
        -> Tool calling
      -> AioSQLiteSessionStore
```

重點：

- 整條請求處理路徑應盡量維持在 async path
- FastAPI 應呼叫 `handle_message_async(...)` 或 `handle_message_stream_async(...)`


## 4. API 分層

對一個正常的 chatbot 後端來說，API 通常不只包含「送一則訊息」而已。

建議至少拆成以下幾組：

1. chat API
2. session API
3. history / query API
4. health / ops API


## 5. Chat API

## 5.1 POST /chat

用途：

- 接收一則使用者訊息
- 回傳一個完整的 assistant 回覆
- 同時保存更新後的 session history

Request body：

```json
{
  "session_id": "user-123",
  "message": "Hello"
}
```

Response body：

```json
{
  "session_id": "user-123",
  "content": "Hello, how can I help?",
  "usage": {
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0
  },
  "tools_used": [],
  "stop_reason": "stop"
}
```

狀態：

- 已實作


## 5.2 GET /chat/stream

用途：

- 接收一則使用者訊息
- 透過 SSE 持續推送 assistant 的增量內容
- 在回答完成後送出最終 metadata
- 同時保存更新後的 session history

Query params：

- `session_id: str`
- `message: str`

SSE event 類型：

1. `delta`
2. `done`
3. `error`

`done` 事件範例：

```json
{
  "session_id": "user-123",
  "content": "Hello, how can I help?",
  "usage": {
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0
  },
  "tools_used": [],
  "stop_reason": "stop"
}
```

狀態：

- 已實作

補充：

- 目前使用 `GET`，主要是因為瀏覽器原生的 `EventSource` 最適合搭配 `GET`
- 後續可以再補 `POST /chat/stream`，用來承接較長的輸入內容


## 5.3 建議後續補充：POST /chat/stream

用途：

- 與 `GET /chat/stream` 功能相同
- 但改用 JSON request body，而不是 query params

這很重要的原因：

- 避免 query string 太長
- 更適合長 prompt
- 後續擴充 request 欄位會更自然

狀態：

- 尚未實作


## 6. Session API

這組 API 對一般 chat UI 很重要，因為前端通常需要顯示對話列表、切換對話、刪除對話。

## 6.1 GET /sessions

用途：

- 列出目前所有已知的 session id

Response body：

```json
{
  "sessions": [
    "default",
    "user-123",
    "user-456"
  ]
}
```

後端依據：

- `LocalAgentRuntime.list_sessions_async()`

優先級：

- 高


## 6.2 DELETE /sessions/{session_id}

用途：

- 清除單一對話 session

Response body：

```json
{
  "session_id": "user-123",
  "deleted": true
}
```

後端依據：

- `LocalAgentRuntime.reset_session_async(session_id)`

優先級：

- 高


## 6.3 建議後續補充：POST /sessions

用途：

- 明確建立一個新的 session id
- 如果前端希望由後端發放 session 物件，這個 API 會很有用

可能回應：

```json
{
  "session_id": "generated-session-id"
}
```

優先級：

- 中

補充：

- 以目前 V1 來說，由前端自行產生 session id 已經足夠


## 7. History / Query API

這組 API 讓前端在重整頁面或切換對話時，可以重新取得既有的對話內容。

## 7.1 GET /sessions/{session_id}/messages

用途：

- 載入某個 session 的完整對話歷史

Response body：

```json
{
  "session_id": "user-123",
  "messages": [
    {"role": "user", "content": "Hello"},
    {"role": "assistant", "content": "Hi"}
  ]
}
```

後端依據：

- `runtime.store.load_history(...)`
- 如果要讓 API 更整潔，後續也可以補 `LocalAgentRuntime.load_history_async(...)`

優先級：

- 高


## 7.2 建議後續補充：GET /sessions/{session_id}

用途：

- 只載入對話摘要 / metadata
- 適合用來渲染側邊欄列表

可能回應：

```json
{
  "session_id": "user-123",
  "message_count": 24,
  "last_message_preview": "Sure, here is the plan...",
  "updated_at": "2026-05-13T22:10:00Z"
}
```

優先級：

- 中

補充：

- 目前 `AioSQLiteSessionStore` 只保存 message，還沒有保存摘要 metadata


## 7.3 建議後續補充：GET /sessions/{session_id}/messages?limit=50&before=...

用途：

- 為長對話提供分頁查詢能力

優先級：

- 中

補充：

- 對目前 MVP 不急
- 當對話量變大時會變得很重要


## 8. Health / Ops API

這組 API 很小，但在實際部署時非常有用。

## 8.1 GET /health

用途：

- 快速檢查服務程序是否正常

Response body：

```json
{
  "status": "ok"
}
```

優先級：

- 高


## 8.2 GET /ready

用途：

- readiness check
- 可選擇順便驗證 config 與 store 是否可用

可能回應：

```json
{
  "status": "ready"
}
```

優先級：

- 中


## 9. 建議的 V1.5 API 組合

如果希望這個後端更像一個正常可用的 chatbot service，下一步最小而實用的 API 集合應該是：

1. `POST /chat`
2. `GET /chat/stream`
3. `GET /sessions`
4. `GET /sessions/{session_id}/messages`
5. `DELETE /sessions/{session_id}`
6. `GET /health`

這組 API 已足夠支援：

- 發送訊息
- 流式顯示回答
- 列出對話列表
- 重新打開舊對話
- 清除單一對話
- 基本服務監控


## 10. 資料模型

目前主要模型：

- `ChatRequest`
  - `session_id: str`
  - `message: str`

- `ChatResponse`
  - `session_id: str`
  - `content: str`
  - `usage: dict[str, int]`
  - `tools_used: list[str]`
  - `stop_reason: str`

- `ChatStreamDone`
  - 與 `ChatResponse` 相同

建議後續新增模型：

- `SessionListResponse`
  - `sessions: list[str]`

- `SessionMessagesResponse`
  - `session_id: str`
  - `messages: list[Message]`

- `DeleteSessionResponse`
  - `session_id: str`
  - `deleted: bool`

- `HealthResponse`
  - `status: str`


## 11. 錯誤處理

建議策略：

- validation error -> HTTP 422
- 已知 request/runtime 錯誤 -> HTTP 400
- not found -> HTTP 404
- 非預期 provider/store/server 錯誤 -> HTTP 500
- SSE 路徑若出錯 -> 發送 `event: error` 後關閉串流


## 12. 檔案結構

建議的 server 結構：

```text
simplified_chatbot/
  server/
    app.py
    schemas.py
    endpoints_chat.py
    endpoints_sessions.py
    endpoints_health.py
    sse.py
```


## 13. 建議的下一步里程碑

### M5.1

實作目前 V1：

1. `POST /chat`
2. `GET /chat/stream`

### M5.2

補上下一組實用 chatbot API：

1. `GET /sessions`
2. `GET /sessions/{session_id}/messages`
3. `DELETE /sessions/{session_id}`
4. `GET /health`

### M5.3

補強正式環境能力：

1. 可選的 `POST /chat/stream`
2. auth
3. rate limit
4. 分頁與 session metadata
