# Picobot Session Memory V1 設計

## 1. 目標

為 `picobot` 增加一層最基礎、可持久化的 session memory，讓長對話在 Web 場景下不只依賴「單純裁減舊 turn」。

這一版明確不做：

- `nanobot` 那種 `Dream` 長期記憶流程
- `SOUL.md` / `USER.md` / `MEMORY.md`
- 多層記憶檔案
- 背景排程整理
- 前端記憶管理 UI

這一版只做：

- 每個 session 一份 rolling summary
- 每個 session 一個 compact cursor
- 完整對話仍保留在 SQLite
- 模型只看 `summary + live tail`
- 壓縮過程可透過 SSE 回傳 event

## 2. 現況

目前 `picobot` 的上下文控制方式如下：

- 完整對話持久化在 `session_messages`
- 每次請求進來時，runtime 先載入完整 history
- 真正送進模型前，`AgentLoop._trim_conversation()` 只會把最舊 turn 從當次 prompt 移除
- 裁掉的內容不會轉成記憶摘要

這代表：

- 對模型而言，舊內容只是「不再送入」
- 對資料層而言，完整對話仍然存在 SQLite
- 缺少一層可復用的「已整理上下文」

## 3. V1 設計原則

### 3.1 最小改動

不先改 `AgentLoop` 主流程，優先把記憶接入點放在 `LocalAgentRuntime`：

- runtime 已負責載入 history
- runtime 已支援 `system_prompt_override`
- runtime 已有 event callback，可直接透給 SSE

### 3.2 單一摘要

每個 session 只保留一份最新 summary，不保留 summary 歷史。

多次壓縮時使用滾動整合策略：

1. 讀取舊 summary
2. 取出新一批待壓縮的舊 turn
3. 讓模型輸出「新的完整 summary」
4. 覆蓋原 summary

因此 DB 中對每個 session 只有：

- 一份最新整理結果
- 一個已吸收訊息數量的 cursor

### 3.3 完整歷史保留

即使已經壓縮，`session_messages` 仍保留完整對話原文。

也就是：

- prompt replay 使用 `summary + 未壓縮尾段`
- SQLite 仍保存完整 message history

這是和 `nanobot` 現階段最重要的差異之一。

## 4. 資料模型

因目前只考慮 `AioSQLite`，建議在同一個 DB 新增一張表。

### 4.1 新表

```sql
CREATE TABLE IF NOT EXISTS session_memory (
    session_id TEXT PRIMARY KEY,
    summary TEXT NOT NULL DEFAULT '',
    compacted_message_count INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);
```

### 4.2 欄位說明

- `session_id`
  對應 `session_messages.session_id`
- `summary`
  目前這個 session 的滾動摘要
- `compacted_message_count`
  代表完整 history 前多少則 message 已經被摘要吸收
- `updated_at`
  最後一次更新時間

### 4.3 為何不直接塞進 `session_metadata`

V1 若只考慮 SQLite，擴欄位 technically 可行，但拆成獨立表更乾淨，原因是：

- session 基本資料與記憶資料責任不同
- 記憶更新頻率較高
- 未來若要增加 debug / inspect API，不需再回頭拆表

## 5. Config 設計

建議在 `config.json` 增加這兩個欄位：

```json
{
  "memoryEnabled": true,
  "memoryCompressionRatio": 0.5
}
```

### 5.1 欄位意義

- `memoryEnabled`
  是否啟用 session memory V1
- `memoryCompressionRatio`
  當超出安全 prompt budget 後，目標將 live context 壓回到 `budget * ratio`

### 5.2 建議預設值

- `memoryEnabled = false`
  先保持完全向後相容
- `memoryCompressionRatio = 0.5`
  與 `nanobot` 預設思路一致，壓回安全預算的 50%

### 5.3 範例

```json
{
  "provider": "openai_compat",
  "model": "gpt-4o-mini",
  "maxTokens": 4000,
  "contextWindowTokens": 32000,
  "maxIterations": 20,
  "temperature": 0.2,
  "workspaceRootDir": "workspaces",
  "memoryEnabled": true,
  "memoryCompressionRatio": 0.5
}
```

## 6. Runtime 流程

### 6.1 讀取階段

每次請求進來後：

1. 載入完整 `history`
2. 載入 `session_memory`
3. 若有 summary：
   - `live_history = history[compacted_message_count:]`
   - 把 summary 注入 `system_prompt_override`
4. 若沒有 summary：
   - `live_history = history`

### 6.2 送模型前

若 `memoryEnabled = true`：

1. 先估算 `summary + live_history + system prompt` 的 token 大小
2. 若未超出 budget：
   - 不做壓縮
3. 若超出 budget：
   - 選出最舊幾個完整 turn 做壓縮
   - 更新 summary 與 `compacted_message_count`
   - 再用新的 `summary + live_history` 呼叫主模型

### 6.3 回寫階段

這一步需要特別小心。

因為主模型收到的 `history` 只會是 `live_history`，所以回傳的 `result.messages` 也只包含：

- live tail
- 本輪新增內容

因此儲存時不能直接覆蓋完整 session history。

正確做法：

1. 取 `prefix = full_history[:compacted_message_count]`
2. 取 `new_full_history = prefix + result.messages`
3. `save_history(session_id, new_full_history)`

這樣才能同時滿足：

- prompt 只看 summary + tail
- DB 繼續保留完整原文

## 7. 壓縮邊界策略

V1 建議直接沿用 `picobot` 現有 turn 概念，不從單條 message 中間切。

### 7.1 切分單位

以 user turn 為單位，保留完整工具鏈。

現有 `AgentLoop._group_conversation_turns()` 已具備這個概念，可重用其思路。

### 7.2 觸發條件

使用與當前 trim 類似的安全預算：

```text
budget = context_window_tokens - max_tokens - safety_buffer
```

其中：

- `context_window_tokens` 來自 config
- `max_tokens` 為輸出預留
- `safety_buffer` 建議沿用目前 `1024`

### 7.3 壓縮目標

若當前估算值超過 `budget`，則把 live context 壓回：

```text
target = budget * memoryCompressionRatio
```

例如：

- `budget = 27000`
- `ratio = 0.5`
- `target = 13500`

runtime 會不斷把最舊 turn 吸收入 summary，直到回到 `target` 左右。

## 8. Summary Prompt

### 8.1 設計方向

壓縮 prompt 可以參考 `nanobot` 的 `consolidator_archive.md`，但要再多一層「merge 現有 summary」能力。

`nanobot` 版本的優點是：

- 強調保留使用者偏好與更正
- 強調保留已驗證有效的方法
- 不記錄可從 source code 直接推導出的內容
- 輸出格式克制

### 8.2 V1 Prompt 草案

建議新增：

`simplified_chatbot/prompts/memory_summary.md`

建議內容：

```md
You are maintaining a compact rolling session memory for an AI coding/web assistant.

Your job is to merge:
1. the existing session summary
2. a batch of older conversation turns that are about to be removed from live context

Keep only durable or reusable context that will help the assistant continue the same session
without the user repeating themselves.

Prioritize:
- User preferences, corrections, and constraints
- Decisions that were made
- Working solutions discovered through trial and error
- Important ongoing tasks or unresolved follow-ups
- Key workspace facts that are still relevant to the current session

Do not keep:
- Conversational filler
- Temporary errors that were already resolved
- Verbatim code that can be re-read from the workspace
- Tool noise
- Duplicate facts already covered in the summary

Output rules:
- Use concise bullet points
- One fact per line
- No preamble
- If nothing important remains, output: (nothing)
```

### 8.3 與 `nanobot` 的差異

V1 不需要 `Dream` 那種：

- long-term file editing
- dedupe across multiple memory files
- skill generation

這裡只要把 session 內值得保留的上下文濃縮成單一 summary 即可。

## 9. SSE / Event 設計

因 `picobot` 主要服務 Web，memory 壓縮過程應回傳 SSE event，避免前端看起來像卡住。

現有 `/chat/stream` 已可原樣轉發 runtime event，因此只需在 runtime emit 新事件。

### 9.1 建議事件

- `memory_compaction_started`
- `memory_compaction_finished`
- `memory_compaction_skipped`
- `memory_compaction_failed`

### 9.2 Payload 範例

開始：

```json
{
  "session_id": "session-1",
  "reason": "prompt_budget_exceeded",
  "estimated_tokens": 41200,
  "budget_tokens": 27000,
  "target_tokens": 13500,
  "compacted_message_count_before": 24
}
```

完成：

```json
{
  "session_id": "session-1",
  "compacted_message_count_before": 24,
  "compacted_message_count_after": 38,
  "summary_chars": 860,
  "summary_updated": true
}
```

跳過：

```json
{
  "session_id": "session-1",
  "reason": "within_budget"
}
```

失敗：

```json
{
  "session_id": "session-1",
  "message": "memory compaction failed",
  "error": "..."
}
```

### 9.3 Event 時序

推薦事件順序：

1. `run_started`
2. `memory_compaction_started` 或 `memory_compaction_skipped`
3. `memory_compaction_finished`
4. 主模型 `llm_call_finished`
5. `delta`
6. `done`

### 9.4 是否需要 summary delta

V1 不需要。

前端只需知道：

- 是否正在整理
- 是否整理完成
- 是否失敗

不需要把 summary 內容本身流給前端。

## 10. 內部抽象建議

建議新增一個非常小的 memory store，不要做成完整 framework。

### 10.1 Dataclass

```python
@dataclass
class SessionMemoryRow:
    session_id: str
    summary: str
    compacted_message_count: int
    updated_at: str
```

### 10.2 Store

新增：

- `AioSQLiteSessionMemoryStore`

建議方法：

- `ensure_schema()`
- `load_memory(session_id: str) -> SessionMemoryRow | None`
- `save_memory(row: SessionMemoryRow) -> None`
- `delete_memory(session_id: str) -> None`

### 10.3 Runtime 內部方法

建議新增：

- `_load_session_memory_async(session_id)`
- `_save_session_memory_async(session_id, summary, compacted_message_count)`
- `_build_memory_augmented_prompt(base_prompt, summary)`
- `_estimate_memory_prompt_tokens(system_prompt, history)`
- `_maybe_compact_memory_async(session_id, full_history, on_event)`
- `_pick_memory_compaction_boundary(history, compacted_message_count, target_tokens)`

## 11. 建議修改檔案

### 必改

- `simplified_chatbot/config/schema.py`
  增加 `memoryEnabled`、`memoryCompressionRatio`
- `simplified_chatbot/runtime/session_store.py`
  增加 `AioSQLiteSessionMemoryStore`
- `simplified_chatbot/runtime/local_runtime.py`
  接入 summary 載入、壓縮、event、prompt override
- `simplified_chatbot/prompts/memory_summary.md`
  新增壓縮用 prompt

### 可能需要

- `simplified_chatbot/server/schemas.py`
  如果前端型別需要顯式列舉新事件
- `README.md`
  補一段記憶 V1 說明
- `example_config.json`
  加入新設定示例

## 12. 測試建議

至少補三類測試：

### 12.1 Store 測試

- `session_memory` schema 建立成功
- `load/save/delete` 正常
- 覆寫更新 `summary` / `compacted_message_count` 正常

### 12.2 Runtime 行為測試

- 開啟 memory 且超 budget 時，會更新 `session_memory`
- 存回 DB 後，`session_messages` 仍保留完整原文
- 下一輪請求只會把 `summary + live tail` 送給模型

### 12.3 SSE 測試

- `chat/stream` 可收到 `memory_compaction_started`
- 可收到 `memory_compaction_finished`
- 壓縮失敗時可收到 `memory_compaction_failed`

## 13. 風險與取捨

### 13.1 只有一份 summary

優點：

- 結構最簡單
- 好實作
- 好注入 prompt

缺點：

- 無法回看每次壓縮的中間版本

V1 接受這個取捨。

### 13.2 完整對話仍保留

優點：

- 可調試
- 可重建
- 不破壞現在 session API

缺點：

- DB 空間成長會比 `nanobot` 類型方案快

V1 先接受，等未來真的需要再做 hard compaction。

### 13.3 壓縮是同步前置步驟

優點：

- 結果立即生效
- 最符合當前 SSE 模型

缺點：

- 首 token 前多一次 LLM 呼叫

因此更需要事件回傳，讓前端知道現在正在整理上下文。

## 14. V1 結論

最小可行方案如下：

1. 新增 `session_memory` 表
2. 每個 session 維護一份 rolling summary
3. 每次請求前用 `summary + live tail` 組 prompt
4. 超 budget 時同步做一次壓縮
5. 完整歷史仍保留在 `session_messages`
6. 壓縮過程透過 SSE 回傳 event

這一版不追求 `nanobot` 的完整 memory 系統，只先解決 `picobot` 在 Web 長對話場景下「單純裁減但沒有整理」的缺口。
