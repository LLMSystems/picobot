# Picobot 聊天介面交互規格

## 0. 文件目的

這份文件描述 picobot 聊天 agent 網頁的**交互行為**，與前端框架無關（React / Vue / Svelte / vanilla 都適用）。

範圍：

- 頁面結構、區塊職責
- 各種使用者操作該如何反應
- 狀態之間怎麼切換
- streaming / tool call / error 的視覺呈現原則
- edge case 的預期行為

不在範圍內：

- 具體選哪個前端框架
- 元件命名、檔案結構
- 樣式 / 配色
- 後端 API 細節（請見 [frontend_api_reference.md](frontend_api_reference.md)）

---

## 1. 頁面整體結構

採用左右兩欄的經典聊天介面：

```
┌─────────────┬───────────────────────────────────────┐
│             │  ① TopBar：標題、目前模型、設定        │
│             ├───────────────────────────────────────┤
│             │                                       │
│  Sidebar    │                                       │
│             │       ② MessageList                   │
│  (對話列表) │       （訊息歷史 / streaming 中的訊息）│
│             │                                       │
│             │                                       │
│             ├───────────────────────────────────────┤
│             │  ③ Composer：輸入框 + 送出 / 停止     │
└─────────────┴───────────────────────────────────────┘
```

### 1.1 區塊職責

| 區塊 | 主要職責 |
| --- | --- |
| Sidebar | 列出歷史對話、開啟新對話、切換、重新命名、刪除 |
| TopBar | 顯示目前對話標題、目前模型、（可選）設定入口 |
| MessageList | 顯示目前對話的全部訊息，包含 user、assistant、tool call |
| Composer | 文字輸入、送出訊息、生成中的停止按鈕 |

### 1.2 響應式

- **桌面寬度**：Sidebar 與主區永遠並排。
- **平板**：Sidebar 預設仍顯示，可手動收合。
- **手機**：Sidebar 預設收合，覆蓋在主區之上；點對話後自動收合。

---

## 2. 應用層狀態

整個前端應該至少維護以下幾組狀態：

### 2.1 全域狀態

- `capabilities`：應用啟動時呼叫 `GET /capabilities` 一次後快取
- `sessions`：對話清單（含 metadata）
- `currentSessionId`：目前選中的對話 id（可為 `null` 代表「未選任何對話」）

### 2.2 對話內狀態

- `messages`：當前對話的訊息陣列
- `streamingMessage`：正在串流中的 assistant 訊息（尚未持久化）
- `pendingToolCalls`：正在執行中的 tool call 陣列
- `runStatus`：`idle` / `streaming` / `error`
- `lastError`：最近一次錯誤訊息

### 2.3 為什麼把 streaming 訊息獨立

`messages` 是後端持久化的歷史，`streamingMessage` 是「進行中還沒寫進 DB 的東西」。把它們分開有兩個好處：

- 收到 `done` 事件時，直接把 streamingMessage 推進 messages、清掉就好
- 如果 stream 中斷，可以選擇丟掉 streamingMessage 或保留為「未完成」狀態，不會污染歷史

---

## 3. 載入與初始化

### 3.1 應用啟動

依序：

1. 呼叫 `GET /health`。失敗 → 顯示「無法連線到後端」全頁錯誤畫面，提供重試按鈕。
2. 呼叫 `GET /capabilities`。失敗 → 不致命，使用預設 fallback（streaming = true、tools = []），並在 UI 標示「能力資訊載入失敗」。
3. 呼叫 `GET /sessions`。
   - 若回傳 `sessions` 非空 → 自動選中 `updated_at` 最新的那一個（或記住上次選的）。
   - 若回傳 `sessions` 為空 → 顯示空狀態畫面（「還沒有對話，按左上『新對話』開始」）。

### 3.2 切換對話

當 `currentSessionId` 改變：

1. 立即清空 `messages` / `streamingMessage`，並顯示骨架載入（skeleton）。
2. 呼叫 `GET /sessions/{id}/messages`。
3. 回來後填入 `messages`，自動滾到底部。
4. 若該 session 還在 streaming（極少見的情況，例如使用者切走又切回），目前後端不支援續接，UI 視為新一輪 idle 即可。

### 3.3 路由

URL 應該能直接定位到對話：

- `/` → 沒選對話
- `/c/{session_id}` → 選中該對話

進入 `/c/{id}` 但該 session 不存在 → 顯示「找不到對話」並提供「回到首頁」按鈕。

---

## 4. Sidebar 行為

### 4.1 對話列表渲染

每一項顯示：

- `title`（過長以省略號截斷，單行）
- `last_assistant_preview` 或 `last_user_message`（過長截斷，單行，灰色字）
- `updated_at`（相對時間：剛剛 / 10 分鐘前 / 昨天 / 5/12）

排序：依 `updated_at` 由新到舊。

### 4.2 高亮目前對話

`session_id === currentSessionId` 的項目要有明顯的選中樣式（背景色 + 左側 indicator）。

### 4.3 新對話按鈕

點擊：

1. 立即在前端建立一個「臨時對話」，UI 切到空白聊天畫面。
2. **不立刻呼叫 `POST /sessions`**，因為使用者可能只是看看就走掉。
3. 等使用者真的送出第一則訊息時，再決定怎麼建立：
   - 方案 A：先呼叫 `POST /sessions` 拿真實 id，再呼叫 `POST /chat/stream`
   - 方案 B：直接呼叫 `POST /chat/stream`，讓後端隱式建立 session

選方案 A 比較乾淨（session 一定先存在），方案 B 比較省一次 round trip。建議方案 A。

### 4.4 重新命名

兩種觸發方式：

- 雙擊標題 → in-place 編輯
- 右鍵 / 三點選單 → 「重新命名」

行為：

1. 點擊 / 雙擊後，標題變成可編輯輸入框，自動 focus 並 select all。
2. 按 Enter 或失焦 → 呼叫 `PATCH /sessions/{id}`，樂觀更新（先改 UI 再呼叫）。
3. 失敗 → 回滾到舊標題，顯示錯誤 toast。
4. 按 Esc → 取消編輯。

### 4.5 刪除

行為：

1. 點刪除 → 跳確認對話框（「確定刪除『xxx』？此操作無法復原」）。
2. 確認後呼叫 `DELETE /sessions/{id}`。
3. 樂觀刪除：先從 sidebar 拿掉。
4. 若刪除的是目前選中的對話，自動切到列表中下一個對話（或回到空狀態）。
5. 失敗 → 把 session 加回列表，顯示錯誤 toast。

### 4.6 空狀態

`sessions` 為空時，sidebar 顯示一個友善訊息與引導按鈕：「還沒有對話 → 開始新對話」。

---

## 5. Composer（輸入框）行為

### 5.1 基本

- 多行 textarea，預設 1 行高，內容增長自動長到最多 8 行，超過後內部捲動。
- placeholder：「輸入訊息...」
- 右下角送出按鈕。

### 5.2 送出條件

送出按鈕在以下情況 disabled：

- 輸入內容為空或全部是空白
- `runStatus === "streaming"`（正在生成中）
- 沒有選中對話且當前不是「新對話」狀態

### 5.3 鍵盤行為

- **Enter** → 送出
- **Shift + Enter** → 換行
- **Esc** → 清空輸入框（如果有內容）；如果正在生成中，等同於按「停止」（見 5.5）
- **↑**（輸入框為空時）→ 把最近一則自己送出的訊息填回輸入框，方便編輯重送

### 5.4 送出後

1. 立即把使用者訊息 append 到 `messages`（樂觀渲染）。
2. 清空輸入框。
3. `runStatus = "streaming"`。
4. 發起 `POST /chat/stream` 串流請求。
5. 滾動到底部。

### 5.5 停止按鈕

當 `runStatus === "streaming"` 時，送出按鈕變成停止按鈕（icon 切換）。

點擊：

1. 前端立即 abort fetch（`AbortController.abort()`）。
2. 把目前已收到的 streamingMessage 標記為「已中止」狀態，仍保留在 UI 中（讓使用者能看到接到一半的內容）。
3. `runStatus = "idle"`。

**注意**：目前後端沒有 abort API，後端 agent loop 還會跑完。視覺上是停了，但實際 token 仍會計費。UI 不要假裝後端真的停了，必要時可在停止訊息旁標一個小提示「（後端可能仍在處理）」。等後端支援 abort 後再移除。

### 5.6 IME 組字保護

中文 / 日文 / 韓文輸入法在組字中按 Enter 不應該觸發送出。判斷 `isComposing` 或 `event.keyCode === 229`。

---

## 6. MessageList 行為

### 6.1 訊息類型

至少要處理三種主要呈現：

- **使用者訊息**：右側對齊（或統一靠左加頭像），背景色和 assistant 不同
- **Assistant 訊息**：左側對齊，支援 markdown 渲染（程式碼區塊、清單、表格、連結）
- **Tool call 區塊**：嵌在 assistant 訊息流程中，視覺上明顯不同（見 §7）

### 6.2 從歷史載入

從 `GET /sessions/{id}/messages` 拿到的 message 陣列：

- `role === "user"` → 一般渲染
- `role === "assistant"` 有 content → 一般渲染
- `role === "assistant"` 有 `tool_calls` 且 content 為空 → 不直接顯示為訊息，但可以把它和下一則 `role === "tool"` 配對成 tool call 區塊（見 §7.3）
- `role === "tool"` → 配對到對應的 assistant tool_call，當作 tool result

預設模式只顯示 user / assistant 文字訊息；「顯示工具細節」開關打開時，才把 tool call 區塊渲染出來。

### 6.3 自動滾動規則

- 新訊息抵達 / streaming delta 進來時：
  - 如果使用者目前**在底部附近**（離底部 < 80px）→ 自動滾到底部
  - 如果使用者**手動向上捲動了**（離底部 ≥ 80px）→ **不要**強制滾動，但在右下角顯示「↓ 新訊息」浮動按鈕，點擊跳到底部

這個規則很重要：不能在使用者往上看歷史時強行把畫面拉到底。

### 6.4 訊息操作

每則訊息 hover 時顯示工具列：

- **複製內容**：複製 markdown 原始文字到剪貼簿
- **（未來）重新生成**：只在 assistant 訊息上顯示，目前後端未支援可灰掉或先不做

### 6.5 空對話狀態

新對話還沒有任何訊息時，顯示：

- 中央大標題「開始一段新對話」
- （可選）幾個建議 prompt 卡片，點擊後直接填入 Composer

---

## 7. Streaming 與 Tool Call 視覺化

### 7.1 SSE 事件對應 UI 動作

| 事件 | UI 動作 |
| --- | --- |
| `run_started` | 在 MessageList 底部建立一個空的 assistant 訊息容器，顯示「思考中...」 |
| `tool_call_started` | 在當前 assistant 訊息內加入一個 tool call 區塊，狀態為「執行中」 |
| `tool_call_finished` | 找到對應 `id` 的 tool call 區塊，狀態改為「完成」/「失敗」，填入 result |
| `delta` | 把 data 文字 append 到當前 assistant 訊息的 content |
| `done` | streamingMessage 寫回 messages，`runStatus = "idle"` |
| `error` | 顯示錯誤訊息，`runStatus = "error"`，停止 stream |

### 7.2 思考中指示

`run_started` 到第一個 `delta` 或 `tool_call_started` 之間，assistant 訊息容器顯示一個閃動的點點或 spinner，配文字「思考中...」。

第一個內容（delta 或 tool call）進來後，這個指示就拿掉。

### 7.3 Tool call 區塊設計

每個 tool call 顯示成一張小卡片，**預設折疊**：

```
┌─────────────────────────────────────────────────┐
│ ⚙ read_file ✓                              [▾] │  ← 折疊狀態
└─────────────────────────────────────────────────┘
```

點開後：

```
┌─────────────────────────────────────────────────┐
│ ⚙ read_file ✓                              [▴] │
├─────────────────────────────────────────────────┤
│ Arguments:                                      │
│   { "path": "README.md" }                       │
│ Result:                                         │
│   # picobot                                     │
│   ...                                           │
└─────────────────────────────────────────────────┘
```

視覺要點：

- 圖標 / 顏色根據 `capabilities.tools[].category` 決定（filesystem、shell、search...）
- 狀態用 icon 表示：
  - 執行中：旋轉的 spinner
  - 成功：✓（綠）
  - 失敗（`ok: false`）：✗（紅）
- `dangerous: true` 的工具（例如 shell）標題加一個小警示色或 icon
- Arguments / Result 用等寬字型
- Result 是字串 → 純文字顯示
- Result 是 object → JSON pretty print
- Result 過長（例如 > 50 行）→ 預設折疊內容，顯示「展開全部 (N lines)」

### 7.4 Delta 渲染

`delta` 的 data 直接 append 到當前 assistant content 字串。每次 append 後 re-render markdown。

效能注意事項：

- markdown 渲染若太頻繁會卡。可以節流到每 50–100ms re-render 一次，或用 incremental markdown parser。
- 程式碼區塊在 stream 中還沒收完三個反引號時，可能會被當成「未閉合」。多數 markdown 渲染器有 tolerant 模式可以處理。

### 7.5 Stream 結束視覺

`done` 後：

- 拿掉「思考中」指示
- 訊息容器底部可以加一行小字顯示 token 用量、用過的工具（可選，預設隱藏，hover 才顯示）
- 滾動到底部一次（如果使用者沒往上看）

---

## 8. 錯誤與例外

### 8.1 分類

| 情境 | 處理 |
| --- | --- |
| 網路完全斷線 | 全局頂部顯示紅色 banner「已斷線，重連中...」，輪詢 `/health` 直到恢復 |
| 後端 4xx（驗證錯誤、找不到 session） | inline 顯示在相關 UI 旁，用 toast 補充 |
| 後端 5xx | toast 顯示「伺服器錯誤」+ request_id，提供「重試」按鈕 |
| SSE 串到一半連線中斷 | 把 streamingMessage 標為「已中斷」，顯示「↻ 重試」按鈕（再送一次相同訊息） |
| 送訊息時沒選對話 | UI 該禁用送出按鈕，防止發生 |

### 8.2 Toast 規範

- 一般通知：3 秒自動消失
- 錯誤：不自動消失，使用者按 X 或新的 toast 蓋掉
- 含 `request_id` 的錯誤要把 request_id 顯示在 toast 內（小字、灰色），方便回報

### 8.3 重試策略

不要自動 retry 失敗的 chat 請求。聊天訊息是用戶意圖，自動重送可能造成重複收費或重複動作。永遠讓使用者顯式按「重試」。

GET 類請求（list sessions、load messages）可以自動 retry 一次，failure 後才顯示錯誤 UI。

---

## 9. 常見 Edge Case

| 情境 | 預期行為 |
| --- | --- |
| 使用者快速連點送出 | 第二次點擊應該被 disabled 阻擋，因為 `runStatus === "streaming"` |
| Streaming 中切換到別的對話 | abort 當前 stream，切過去新對話載入。原對話的 streamingMessage 直接丟棄 |
| Streaming 中刪除當前對話 | 先 abort stream，再呼叫 DELETE |
| Streaming 中關閉瀏覽器分頁 | 瀏覽器自動關 fetch；後端會繼續跑完（目前限制） |
| 送出非常長的訊息（> 10000 字） | 不擋，POST body 可以承受。後端會拒絕的話顯示其錯誤訊息 |
| 訊息 markdown 內含惡意 HTML / script | markdown 渲染器必須開 sanitize（最低標：禁止 `<script>` 與 inline event handler） |
| 程式碼區塊內有超長單行 | 預設水平捲動，不要強制換行（會破壞縮排） |
| 訊息含長 URL | 自動轉成可點連結；連結要有 `rel="noopener noreferrer"` |
| `tool_call_finished.result` 是 100KB 字串 | 預設只顯示前 N 行，提供「展開全部」 |
| 點 sidebar 列表時對話正在 streaming | 切過去前先 abort 當前 stream |

---

## 10. 鍵盤快捷鍵

建議至少支援：

| 快捷鍵 | 動作 |
| --- | --- |
| `Cmd/Ctrl + K` | 開啟搜尋 / 命令面板（如果有做） |
| `Cmd/Ctrl + N` | 新對話 |
| `Cmd/Ctrl + Backspace` | 刪除目前對話（需確認） |
| `Esc` | 取消 Composer 內容 / 停止生成 |
| `Cmd/Ctrl + ↑` / `↓` | 在 sidebar 對話間切換 |
| `/` | focus 到輸入框 |

組字中（IME composition）不觸發任何快捷鍵。

---

## 11. 無障礙（A11y）

最低標：

- 所有按鈕有 `aria-label`
- Sidebar 對話列表用 `<ul>` / `<li>` 或 `role="listbox"`，當前選中項用 `aria-selected="true"`
- MessageList 用 `role="log"` 與 `aria-live="polite"`，讓螢幕閱讀器在新訊息進來時讀出
- streaming delta 不要每個 token 都 announce（會吵），建議只在 `done` 時 announce 一次完整訊息
- 顏色對比 ≥ WCAG AA
- 鍵盤可以單獨完成所有核心操作（新對話、切換、送出、停止、刪除）

---

## 12. 視覺與動效原則

- **不過度動畫**：訊息出現用 fade-in 或微小 slide-up 即可；不要彈跳、不要 shake
- **狀態切換要有可預期的動效**：例如送出按鈕變停止按鈕，用 100–150ms 的 crossfade，而不是瞬間切換
- **Skeleton 載入**：切換對話、初次載入訊息列表時用骨架屏，而不是 spinner
- **Streaming 游標**：assistant 正在 delta 接收時，內容末端閃動一個小游標 `▍`，給「正在打字」的感覺
- **不要 layout shift**：tool call 區塊從「執行中」變「完成」時高度不能跳動，預先給 placeholder

---

## 13. 開發者模式（可選）

對 debug 友善的隱藏入口：

- 設定中或 `?dev=1` 啟動「開發者模式」
- 啟用後 MessageList 顯示：
  - 每則訊息的 id、created_at、token 用量
  - SSE 原始事件 log（側邊 drawer）
  - 失敗時的 request_id 直接顯示
- 一般使用者看不到，但開發 / 除錯時極有用

---

## 14. 一句話總結每個區塊該做什麼

- **Sidebar**：永遠列出目前所有對話、清楚標出哪個是當前對話、提供新增 / 改名 / 刪除
- **TopBar**：顯示「現在我在哪個對話、用什麼模型」
- **MessageList**：忠實重現對話流程，streaming 與 tool call 必須可視化且不打擾閱讀
- **Composer**：永遠告訴使用者「現在能不能送、送了會怎樣、能不能停」

如果這四件事都做對，前端就成功了一半。
