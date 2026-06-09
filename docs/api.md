# API Reference

除 `/auth/*`、`/capabilities`、`/health` 外，其餘端點都需登入（cookie session）。`/metrics/*`、`/alerts/*`、`/mcp/*` 另需管理者。所有 `/sessions/{id}/...` 只有 owner 能存取，否則回 404。

## Auth

- `POST /auth/register` — 註冊並直接登入（set cookie）
- `POST /auth/login` — 登入
- `POST /auth/logout` — 登出
- `GET /auth/me` — 取得目前使用者（含 `is_admin`）

## Chat

- `POST /chat` — 非串流，回完整回答與 trace events
- `GET /chat/stream` — SSE 串流
- `POST /chat/stream` — SSE 串流，使用 JSON body

## Session

- `GET /sessions` — 取得自己的 session 清單與 metadata
- `POST /sessions` — 建立空白 session
- `PATCH /sessions/{session_id}` — 更新 session title
- `GET /sessions/{session_id}/messages` — 取得完整歷史訊息
- `GET /sessions/{session_id}/subagents` — 取得該 session 的 subagent runs
- `GET /sessions/{session_id}/subagents/{task_id}` — 取得單一 subagent summary
- `GET /sessions/{session_id}/subagents/{task_id}/events` — 取得單一 subagent timeline events
- `GET /sessions/{session_id}/events/stream` — SSE 推送背景事件（subagent progress 等）
- `DELETE /sessions/{session_id}` — 刪除 session

## Workspace

- `GET /sessions/{session_id}/workspace/tree` — 列出 workspace 目錄內容
- `GET /sessions/{session_id}/workspace/file` — 讀取 workspace 中的 UTF-8 文字檔
- `POST .../workspace/upload`、`PUT/POST .../file`、`POST .../mkdir`、`POST .../move`、`DELETE .../file`、`DELETE .../directory`、`GET .../download` — 上傳 / 建立 / 改名 / 刪除 / 下載

## Skills（per-user）

- `GET /skills`、`POST /skills`、`DELETE /skills/{name}`、`PATCH /skills/{name}` — 列出 / 建立 / 刪除 / 停用自己的 skills（builtin 與共用 skills 唯讀）

## 管理者 API（admin-only）

- `GET /metrics/current`、`/metrics/history`、`/metrics/stream`(SSE)、`/metrics/sessions/{id}`
- `GET /alerts/active`、`/alerts/history`、`/alerts/rules`、`/alerts/stream`(SSE)、`POST /alerts/...`（ack / 靜音）
- `GET /mcp/status`、`POST /mcp/reload`、`GET /mcp/servers`、`PUT/DELETE /mcp/servers/{name}`

## Capability / Health（公開）

- `GET /capabilities` — 回傳 model、tools、feature flags
- `GET /health` — 健康檢查

## 串流事件

`/chat/stream` 透過 SSE 回傳：

| 事件 | 說明 |
|------|------|
| `run_started` | agent 開始執行 |
| `tool_call_started` | 工具呼叫開始 |
| `tool_call_finished` | 工具呼叫結束（含結果） |
| `workspace_changed` | workspace 檔案有異動 |
| `delta` | 文字串流片段 |
| `done` | 串流結束（含完整 usage） |
| `error` | 發生錯誤 |

`/sessions/{session_id}/events/stream` 會額外推送背景 subagent 事件：

| 事件 | 說明 |
|------|------|
| `subagent_spawned` | 子代理建立 |
| `subagent_phase_changed` | 子代理 phase 更新 |
| `subagent_delta` | 子代理串流文字片段 |
| `subagent_tool_call_started` | 子代理工具呼叫開始 |
| `subagent_tool_call_finished` | 子代理工具呼叫結束 |
| `subagent_iteration_completed` | 子代理完成一輪 iteration |
| `subagent_completed` | 子代理成功完成 |
| `subagent_failed` | 子代理失敗 |
| `subagent_cancelled` | 子代理被取消 |

## 內建工具

- **檔案 / 搜尋**：`read_file`、`write_file`、`edit_file`、`apply_patch`、`list_dir`、`find_files`、`glob`、`grep`
- **文件 / 圖片讀取**：`read_pdf`、`read_docx`、`read_xlsx`、`view_image`
- **Shell / 執行**：`exec`、`write_stdin`、`list_exec_sessions`（裝了 bubblewrap 時於沙箱內執行）
- **Web**：`tavily_search`、`web_fetch`
- **Subagent control**：`spawn`、`list_subagents`、`subagent_status`、`subagent_wait`、`cancel_subagent`
- **互動 / 規劃**：`ask_user_question`、`todo_write`

備註：

- `apply_patch` 用於多檔案、結構化批次修改，支援 `dry_run=true`
- `exec(..., yield_time_ms=...)` 可啟動可持續互動的 exec session；`write_stdin` / `list_exec_sessions` 用於接續或找回執行中命令
- skills 不再透過 `read_skill` 讀取：session 啟動時會把可用 skills 複製到 workspace 的 `.skills/`，agent 直接以 `read_file` 讀取（`read_skill` 已棄用）
