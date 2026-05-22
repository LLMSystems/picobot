<div align="center">


<p align="center">
  <img src="assets/image0.png" width="500px" style="vertical-align:middle;">
</p>



`picobot` 是一個輕量 agent 專案，目標是用清楚、可擴展的方式，實作一個可聊天、可調工具、可操作 workspace、操作網頁、搜尋資料的 Web agent。

![web0](assets/web_image0.png)
![web1](assets/image1.png)

</div>

---

## 1. 功能概覽

**後端 / Agent**

- 可配置的聊天與 異 agent 執行核心
- 資料庫以 SQL 為主
- 可調用工具、瀏覽網頁的多輪互動能力
- session 與 per-session workspace 管理
- 可直接掛到 FastAPI 的後端 API
- 可逐步擴充的 skills、prompt、eval 架構

**前端 Web UI**

- 多 session 管理（建立、重新命名、刪除）
- SSE 串流即時顯示 AI 回答
- Markdown 完整渲染（粗體、斜體、程式碼塊、表格、Mermaid 圖表）
- 工具呼叫視覺化（展示 agent 每次 tool call 的輸入輸出）
- Workspace 面板（檔案樹 + 檔案預覽，支援語法高亮）
- 可拖拉調整寬度的三欄版面（sidebar、主聊天、workspace）
- 全螢幕檔案預覽 Modal
- 深色 / 淺色主題切換

---

## 2. 專案架構

```text
picobot/
  simplified_chatbot/
    agent/          # agent loop, message flow, run result
    config/         # config schema / loader / env handling
    prompts/        # system prompt 與 prompt 組裝
    providers/      # OpenAI-compatible provider
    runtime/        # session runtime, store, workspace 管理
    server/         # FastAPI endpoints 與 schemas
    skills/         # builtin / workspace skills loader
    tools/          # file, search, shell, skill tools
  frontend/
    src/
      components/   # chat、layout、workspace、common UI 元件
      composables/  # useAutoScroll、useHorizontalResize、useVerticalSplit 等
      lib/          # api、sse、markdown、types
      stores/       # Pinia stores（capabilities、sessions、chat、workspace）
      views/        # ChatView、EmptyView
  eval/             # eval datasets, runs, scripts
  tests/            # pytest 測試
  README.md
  pyproject.toml
```

---

## 3. 驗測結果

目前 `picobot` 的評測分成兩組資料集：
- core agent 題庫：[agent_core_21.jsonl](eval/datasets/agent_core_21.jsonl)
- browser 題庫：[browser_core_4.jsonl](eval/datasets/browser_core_4.jsonl)

對應的執行方式如下：

```bash
python3 eval/scripts/run_eval.py example_config.json eval/datasets/agent_core_21.jsonl
python3 eval/scripts/run_eval.py example_config.json eval/datasets/browser_core_4.jsonl --enable-llm-judge --judge-model gpt-4.1-mini
```

目前已用 gpt-5-mini 進行一輪本地 eval 驗測，目前驗測題目共有 25 題，可參考 [runs](eval/runs)：
- core agent 題 21 題
- browser 題 4 題

這 25 題覆蓋的能力包含：
- 多輪 agent loop 與工具調用
- workspace 內的讀寫、搜尋、整理與產物生成
- 網站瀏覽、點擊與截圖驗證

目前的整體結果可分成兩層理解：
- 純 rule-based 統計：24 / 25 通過，`pass_rate = 0.96`
- final 統計：25 / 25 通過，`pass_rate = 1.0`
- 細項:
  - `tool_calling` 類題目 `8 / 8` 通過
  - `workspace` 類題目 `13 / 13` 通過
  - `browser` 類題目 `4 / 4` 通過

差異來自 browser 題型。browser 題的操作流程高度開放，即使是同一任務，也可能出現不同但合理的 CLI 操作序列，因此這類題目不只看固定字串規則，而是同時參考 (使用 llm-as-judge 進行評估)：
- 題目本身
- agent 最終回答
- workspace 產出的文字 artifact
- 最終 screenshot
- `agent-browser` skill 規則

在這個前提下，browser 題會同時產生三種結果：
- `rule_pass`：只看檔案存在、文字命中、圖片大小等規則
- `llm_judge_pass`：由支援圖片輸入的 judge model 綜合判斷
- `final_pass`：browser 題以 `llm_judge_pass` 為最終結果，其他題型則沿用 rule-based 結果

目前的 eval runner 會為每一題建立獨立 `session_id`，並配對自己的 session workspace。也就是說，每題都是在隔離的 agent 執行環境下進行驗證，而不是共用同一份對話歷史或工作目錄。這讓評測更接近實際部署情境，也能避免前一題留下的檔案或上下文污染後一題。

每次執行 `run_eval.py` 後，都會在 [eval/runs](eval/runs) 下產生一個新的 run 目錄，命名類似：

```text
eval/runs/2026-05-17_232301/
```

典型結構如下：

```text
eval/runs/<run_id>/
  config_snapshot.json
  dataset_snapshot.jsonl
  run.json
  cases/
    <case_id>.json
  sessions/
    <session_id>.jsonl
  workspaces/
    <session_id>/
```

各檔案用途如下：
- `run.json`：整體 summary，包含完成數、通過率、分類統計與每題摘要。
- `cases/<case_id>.json`：單題完整結果，包含最終回答、工具使用、events、workspace outputs、rule-based score，以及 browser 題的 `llm_judge` 與 `final_pass`。
- `config_snapshot.json`：當次 run 使用的設定快照，方便之後重現。
- `dataset_snapshot.jsonl`：當次 run 實際使用的題庫快照，避免資料集後續變更造成結果不可追溯。
- `sessions/<session_id>.jsonl`：該題對話歷史。
- `workspaces/<session_id>/`：該題實際執行後留下的 workspace，可直接檢查 agent 生成的檔案與 artifact。

---

## 4. 快速開始

### 4.1 安裝後端

需求：Python 3.11 以上

```bash
python3 -m pip install -e .
```

### 4.2 設定 API Key

請在專案根目錄建立 `.env`：

```env
OPENAI_API_KEY=your_api_key_here
CORS_ALLOWED_ORIGINS=web_url_here
TAVILY_API_KEY=tvly-your_api_key_here
```

可選：

```env
OPENAI_BASE_URL=http://localhost:11434/v1
```

### 4.3 範例設定檔

`example_config.json`：

```json
{
  "provider": "openai_compat",
  "model": "gpt-4.1-mini",
  "maxTokens": 2000,
  "contextWindowTokens": 32000,
  "maxIterations": 20,
  "temperature": 0.2,
  "workspaceRootDir": "workspaces"
}
```

### 4.4 啟動後端 Server

```bash
python3 fastapi_server.py --config example_config.json --host 0.0.0.0 --port 8000
```

或是

```sh
sh start_fastapi_server.sh
```

若容器要對外提供服務：

```sh
HOST=0.0.0.0 PORT=8000 sh start_fastapi_server.sh
```

### 4.5 啟動前端

需求：Node.js 18 以上

```bash
cd frontend
npm install
npm run dev
```

預設會在 `http://localhost:5173` 啟動。前端預設將 API 請求代理到 `http://localhost:8000`，可在 `frontend/vite.config.ts` 調整。

正式部署時可用：

```bash
npm run build
```

產出靜態檔案在 `frontend/dist/`，可直接由後端或任意靜態伺服器提供服務。

### 4.6 使用 LocalAgentRuntime（純 Python）

```python
import asyncio

from simplified_chatbot.runtime.local_runtime import LocalAgentRuntime


async def main() -> None:
    runtime = LocalAgentRuntime.from_config("example_config.json")

    first = await runtime.handle_message_async(
        session_id="demo-session",
        message="你好，請先簡單介紹你自己。",
    )
    print("Assistant:", first.content)

    second = await runtime.handle_message_async(
        session_id="demo-session",
        message="請延續上一輪，再用一句話介紹你目前有哪些工具能力。",
    )
    print("Assistant:", second.content)


if __name__ == "__main__":
    asyncio.run(main())
```

### 4.7 測試

```bash
python3 -m pytest tests -q
```

---

## 5. 前端功能說明

### 5.1 多 Session 管理

左側 Sidebar 列出所有對話，可：

- 點擊「新增對話」建立空白 session
- 點擊 session 切換對話
- 右鍵或點選選單可重新命名、刪除

### 5.2 串流聊天

訊息送出後透過 SSE 即時顯示 AI 回答，支援：

- 串流中顯示打字游標
- 串流中即時渲染 Markdown
- 按 `Escape` 或點擊停止按鈕中斷串流

**Composer 快捷鍵**

| 按鍵 | 動作 |
|------|------|
| `Enter` | 送出訊息 |
| `Shift + Enter` | 換行 |
| `Escape` | 停止串流 / 清空輸入框 |
| `↑`（空白時） | 帶回上一則使用者訊息 |

### 5.3 Markdown 渲染

AI 回答支援完整 Markdown，包含：

- 粗體（`**text**`）、斜體（`*text*`）
- 程式碼塊（含語法高亮，支援 30+ 語言）
- 表格、引用、水平線
- Mermaid 圖表（`flowchart`、`sequenceDiagram` 等）
- 行內程式碼

### 5.4 工具呼叫視覺化

Agent 每次呼叫工具時，訊息中會顯示 ToolCall 卡片，包含工具名稱、輸入參數、執行結果，可展開查看詳情。

### 5.5 Workspace 面板

當後端 capabilities 回傳 `session_workspace: true` 時，右側會出現 Workspace 面板：

- **檔案樹**：展開 / 收合資料夾，點擊即可預覽檔案
- **檔案預覽**：
  - Markdown 檔案：完整 Markdown 渲染（含 Mermaid）
  - 程式碼檔案：語法高亮（highlight.js）
  - 一鍵複製檔案內容
  - 全螢幕預覽（90vw × 85vh Modal）
  - 超長檔案支援「載入更多」分頁

Workspace 會監聽串流中的 `workspace_changed` 事件，AI 操作檔案後自動刷新。

### 5.6 可拖拉版面

三欄式版面均可用滑鼠拖拉調整：

| 區域 | 方向 | 最小 / 最大 |
|------|------|------------|
| 左側 Sidebar | 水平（右邊緣） | 180px / 60vw |
| Workspace 面板 | 水平（左邊緣） | 240px / 60vw |
| Workspace 檔案樹 / 預覽 | 垂直 | 15% / 85% |

寬度 / 比例會自動儲存至 `localStorage`。

### 5.7 主題切換

右上角提供深色 / 淺色主題切換，設定儲存至 `localStorage`。

---

## 6. API 摘要

### Chat

- `POST /chat` — 非串流，回完整回答與 trace events
- `GET /chat/stream` — SSE 串流
- `POST /chat/stream` — SSE 串流，使用 JSON body

### Session

- `GET /sessions` — 取得 session 清單與 metadata
- `POST /sessions` — 建立空白 session
- `PATCH /sessions/{session_id}` — 更新 session title
- `GET /sessions/{session_id}/messages` — 取得完整歷史訊息
- `DELETE /sessions/{session_id}` — 刪除 session

### Workspace

- `GET /sessions/{session_id}/workspace/tree` — 列出 workspace 目錄內容
- `GET /sessions/{session_id}/workspace/file` — 讀取 workspace 中的 UTF-8 文字檔

### Capability / Health

- `GET /capabilities` — 回傳 model、tools、feature flags
- `GET /health` — 健康檢查

### 串流事件

`/chat/stream` 透過 SSE 回傳以下事件：

| 事件 | 說明 |
|------|------|
| `run_started` | agent 開始執行 |
| `tool_call_started` | 工具呼叫開始 |
| `tool_call_finished` | 工具呼叫結束（含結果） |
| `workspace_changed` | workspace 檔案有異動 |
| `delta` | 文字串流片段 |
| `done` | 串流結束（含完整 usage） |
| `error` | 發生錯誤 |

---

## 7. 前端技術棧

| 分類 | 套件 |
|------|------|
| 框架 | Vue 3 + TypeScript |
| 建構 | Vite |
| 狀態管理 | Pinia |
| UI 元件 | shadcn-vue |
| 樣式 | Tailwind CSS v4 |
| Markdown | markdown-it + DOMPurify |
| 語法高亮 | highlight.js |
| 圖表 | Mermaid |

---

## 8. 感謝

`picobot` 的整體架構設計主要參考了 [nanobot](https://github.com/HKUDS/nanobot)，特別是在以下方向上受到啟發：

- agent loop 的設計思路
- tool calling 形式
- skills 機制
- prompt 分層概念
- workspace / runtime 導向的 agent 架構

同時，`picobot` 也和 `nanobot` 有著不同的特色：

- 更小的開發範圍
  - 主要專注在 agent 最核心的執行框架，更易閱讀、理解
- 基於異步構建 Agent : 對 web chatbot / agent UI 、多併發整合更友善
- 有明確的 per-session workspace 路線
  - 對 web chatbot / agent UI 的整合更簡單

對 `nanobot` 表示感謝，是這個專案得以快速長出可靠骨架的重要原因。`picobot` 會繼續沿著這條路，維持「小而清楚，但可持續擴展」的方向演進。
