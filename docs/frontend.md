# 前端功能說明

## 登入 / 帳號

- 登入 / 註冊頁，未登入自動導向；任一 API 回 401 即清狀態並回登入。
- 左下角帳號選單（ChatGPT 風格）：設定、深淺主題切換、通知開關、登出。主題設定存於 `localStorage`。
- Dashboard 切換與告警鈴僅管理者可見。

## 多 Session 管理

左側 Sidebar 列出自己的對話，可：新增空白 session、切換、重新命名、刪除。

## 串流聊天

訊息送出後透過 SSE 即時顯示 AI 回答：串流中打字游標、即時渲染 Markdown、`Escape` 或停止按鈕中斷。

**Composer 快捷鍵**

| 按鍵 | 動作 |
|------|------|
| `Enter` | 送出訊息 |
| `Shift + Enter` | 換行 |
| `Escape` | 停止串流 / 清空輸入框 |
| `↑`（空白時） | 帶回上一則使用者訊息 |

## Markdown 渲染

粗體 / 斜體、程式碼塊（語法高亮，30+ 語言）、表格 / 引用 / 水平線、Mermaid 圖表、行內程式碼。

## 工具呼叫視覺化

Agent 每次呼叫工具時，訊息中顯示 ToolCall 卡片（工具名稱、輸入參數、執行結果），可展開查看。

## Subagent 面板

Workspace 區整合 Subagent Panel：列出目前 session 的 subagent summary、running/done/failed 數量、最近使用工具與即時輸出，可展開看 timeline 與最終結果。資料來源：

- **reload recovery**：`GET /sessions/{id}/subagents` 與 `.../events`
- **live updates**：`GET /sessions/{id}/events/stream`

即使重新整理頁面也能恢復既有狀態再接續即時更新。

## Workspace 面板

當後端 capabilities 回傳 `session_workspace: true` 時出現：

- **檔案樹**：展開 / 收合、點擊預覽
- **檔案預覽**：Markdown 完整渲染（含 Mermaid）、程式碼語法高亮、一鍵複製、全螢幕 Modal、超長檔案分頁

監聽串流的 `workspace_changed` 事件，AI 操作檔案後自動刷新。

## 可拖拉版面

| 區域 | 方向 | 最小 / 最大 |
|------|------|------------|
| 左側 Sidebar | 水平（右邊緣） | 180px / 60vw |
| Workspace 面板 | 水平（左邊緣） | 240px / 60vw |
| Workspace 檔案樹 / 預覽 | 垂直 | 15% / 85% |

寬度 / 比例自動儲存至 `localStorage`。

## Dashboard / Alerts（admin）

- **Dashboard**：系統健康總覽、System / Agent / API 即時指標、echarts 趨勢圖（1h/24h/7d）、Per-session drill-down、Top tools / endpoints / Recent activity、Token by-model；左側 sticky anchor rail 導覽。
- **Alerts**：進行中告警卡（ack / 靜音 1h/6h/24h/7d）、歷史過濾與展開、跳轉對應趨勢圖、規則一覽 collapsible card；warning+ 自動 browser push。
