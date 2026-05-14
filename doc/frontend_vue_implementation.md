# Picobot 前端實作文檔（Vue 3 + shadcn-vue + Tailwind v4）

## 0. 文件定位

這份文件是 [frontend_interaction_spec.md](frontend_interaction_spec.md) 的**實作對應版**。

- 交互規格回答「**該怎麼運作**」
- 本文件回答「**Vue 3 / shadcn-vue / Tailwind v4 下要怎麼寫**」

對應的後端 API 細節請見 [frontend_api_reference.md](frontend_api_reference.md)。

---

## 1. 技術棧確認

| 項目 | 使用 |
| --- | --- |
| 框架 | Vue 3.5（`<script setup>` + Composition API） |
| 型別 | TypeScript（嚴格 + `noUncheckedIndexedAccess`） |
| 狀態管理 | Pinia 3 |
| 路由 | Vue Router |
| UI | shadcn-vue（style: new-york，base color: neutral，font: Inter） |
| 元件底層 | Reka UI（被 shadcn-vue 包裝） |
| CSS | Tailwind CSS v4（透過 `@tailwindcss/vite` 載入） |
| Icon | `lucide-vue-next` |
| 構建 | Vite 8 |
| Lint | oxlint + eslint + prettier |

專案位置：[frontend/](../frontend/)

---

## 2. 目錄結構規劃

在現有腳手架上補成：

```
frontend/src/
├── assets/
│   └── main.css                  # tailwind v4 + shadcn theme
├── components/
│   ├── ui/                       # shadcn-vue 安裝的元件（不手改）
│   ├── layout/
│   │   ├── AppShell.vue          # 整體 grid（sidebar + main）
│   │   ├── Sidebar.vue
│   │   └── TopBar.vue
│   ├── sessions/
│   │   ├── SessionList.vue
│   │   ├── SessionItem.vue
│   │   └── SessionActions.vue    # rename / delete 選單
│   ├── chat/
│   │   ├── MessageList.vue
│   │   ├── MessageItem.vue
│   │   ├── UserMessage.vue
│   │   ├── AssistantMessage.vue
│   │   ├── ToolCallCard.vue
│   │   ├── Composer.vue
│   │   ├── StreamingCursor.vue
│   │   └── EmptyState.vue
│   └── common/
│       ├── MarkdownView.vue
│       ├── ScrollToBottom.vue
│       └── ConnectionBanner.vue
├── composables/
│   ├── useChatStream.ts          # POST /chat/stream + SSE 解析
│   ├── useAutoScroll.ts          # MessageList 自動滾動
│   ├── useShortcuts.ts           # 全域快捷鍵
│   └── useRelativeTime.ts        # "10 分鐘前"
├── lib/
│   ├── api.ts                    # 所有 HTTP 呼叫
│   ├── sse.ts                    # SSE parser
│   ├── markdown.ts               # markdown 渲染 + sanitize
│   ├── types.ts                  # 與後端對應的 TS 型別
│   ├── errors.ts                 # 統一錯誤類別
│   └── utils.ts                  # shadcn 預設 cn() 等
├── stores/
│   ├── capabilities.ts
│   ├── sessions.ts
│   └── chat.ts
├── router/
│   └── index.ts
├── views/
│   ├── ChatView.vue              # /c/:id
│   └── EmptyView.vue             # /
├── App.vue
└── main.ts
```

幾個重點：

- `components/ui/` 是 shadcn-vue 安裝出來的原始檔，**不要直接改**，要客製就 wrap 一層放到 `components/common/` 或對應領域資料夾。
- `composables/` 是 shadcn-vue 預設別名（已在 `components.json` 設好）。
- views 對應路由頁面，元件對應可重用區塊。

---

## 3. 需要安裝的 shadcn-vue 元件

進入 `frontend/` 後：

```bash
npx shadcn-vue@latest add button input textarea
npx shadcn-vue@latest add scroll-area separator
npx shadcn-vue@latest add dialog dropdown-menu context-menu
npx shadcn-vue@latest add tooltip toast sonner
npx shadcn-vue@latest add skeleton badge avatar
npx shadcn-vue@latest add command  # 給 Cmd+K 命令面板（之後可加）
npx shadcn-vue@latest add collapsible  # tool call 卡片折疊
```

對應用途：

| shadcn 元件 | 用在哪 |
| --- | --- |
| `Button` | 各處按鈕 |
| `Textarea` | Composer 輸入 |
| `ScrollArea` | MessageList / Sidebar 捲動容器 |
| `Dialog` | 刪除確認、設定 |
| `DropdownMenu` / `ContextMenu` | Session 三點選單、右鍵 |
| `Tooltip` | icon button 提示 |
| `Sonner` | Toast 通知（推薦 Sonner 而非舊版 Toast） |
| `Skeleton` | 訊息載入骨架 |
| `Badge` | 工具標籤、危險工具標示 |
| `Collapsible` | Tool call 卡片展開折疊 |

---

## 4. Tailwind v4 與主題

Tailwind v4 的 CSS 入口（`src/assets/main.css`）會是這種形式：

```css
@import "tailwindcss";
@import "tw-animate-css";

@custom-variant dark (&:is(.dark *));

:root {
  --background: oklch(1 0 0);
  --foreground: oklch(0.15 0 0);
  /* ... shadcn-vue 安裝時會自動填入 neutral 主題的 token */
}

.dark {
  --background: oklch(0.15 0 0);
  --foreground: oklch(0.98 0 0);
  /* ... */
}

@theme inline {
  --color-background: var(--background);
  --color-foreground: var(--foreground);
  /* ... shadcn 會 map 進來 */
}

@layer base {
  html { font-family: "Inter", system-ui, sans-serif; }
  body { @apply bg-background text-foreground antialiased; }
}
```

要點：

- shadcn-vue init 之後這份 CSS 大致已經有了，**不要重寫**，只在需要時加自訂 token。
- 暗色模式：把 `dark` class 切到 `<html>` 上即可（之後做 theme toggle 時實作）。
- 字體 Inter 已選，記得在 `index.html` 加 preload 或用 Google Fonts，shadcn-vue 可能已處理。

---

## 5. TypeScript 型別（`lib/types.ts`）

對應後端 schema：

```ts
export interface Capabilities {
  model: { provider: string; name: string }
  max_iterations: number
  tools: ToolCapability[]
  features: {
    streaming: boolean
    session_workspace: boolean
    file_upload: boolean
    multimodal: boolean
  }
}

export interface ToolCapability {
  name: string
  description: string
  category: "filesystem" | "shell" | "search" | string
  dangerous: boolean
}

export interface SessionSummary {
  session_id: string
  title: string
  created_at: string
  updated_at: string
  message_count: number
  last_user_message: string
  last_assistant_preview: string
}

export type MessageRole = "user" | "assistant" | "tool" | "system"

export interface BaseMessage {
  id: string
  role: MessageRole
  content: string
  created_at: string
}

export interface AssistantMessage extends BaseMessage {
  role: "assistant"
  tool_calls?: ToolCallRef[]
}

export interface ToolMessage extends BaseMessage {
  role: "tool"
  tool_call_id: string
  name: string
}

export type SessionMessage = BaseMessage | AssistantMessage | ToolMessage

export interface ToolCallRef {
  id: string
  type: "function"
  function: { name: string; arguments: string }
}

export interface ChatUsage {
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
}

export interface ChatTraceEvent<T = unknown> {
  event: string
  data: T
}

export interface ApiErrorBody {
  error: { code: string; message: string; request_id: string }
}

// SSE 事件 payload
export interface RunStartedData { session_id: string; message: string }
export interface ToolCallStartedData {
  id: string; name: string; arguments: Record<string, unknown>
}
export interface ToolCallFinishedData {
  id: string; name: string; ok: boolean; result: unknown
}
export interface DoneData {
  session_id: string
  content: string
  usage: ChatUsage
  tools_used: string[]
  stop_reason: "stop" | "max_iterations" | string
}
export interface StreamErrorData {
  code: string; message: string; request_id: string
}

// 前端內部：對話中的「視覺訊息」，包含進行中的 tool calls
export interface DisplayMessage {
  id: string
  role: "user" | "assistant"
  content: string
  created_at: string
  toolCalls: DisplayToolCall[]
  status: "complete" | "streaming" | "aborted" | "error"
  usage?: ChatUsage
  toolsUsed?: string[]
}

export interface DisplayToolCall {
  id: string
  name: string
  arguments: Record<string, unknown>
  result?: unknown
  ok?: boolean
  status: "running" | "ok" | "failed"
}
```

`DisplayMessage` 與後端 `SessionMessage` 是有意分開的：前者是 UI 形狀（已 pair 好 tool call），後者是後端 raw 形狀。從 history 載入時要做轉換。

---

## 6. API 層（`lib/api.ts`）

集中所有 HTTP 呼叫，不要散在元件裡。

```ts
import type {
  Capabilities, SessionSummary, SessionMessage, ApiErrorBody,
} from "./types"
import { ApiError } from "./errors"

const BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000"

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  })
  const requestId = res.headers.get("X-Request-Id") ?? undefined
  if (!res.ok) {
    let body: ApiErrorBody | undefined
    try { body = await res.json() } catch { /* ignore */ }
    throw new ApiError(
      body?.error?.code ?? "UNKNOWN",
      body?.error?.message ?? res.statusText,
      body?.error?.request_id ?? requestId,
      res.status,
    )
  }
  return (await res.json()) as T
}

export const api = {
  health: () => request<{ status: string }>("/health"),
  capabilities: () => request<Capabilities>("/capabilities"),

  listSessions: () =>
    request<{ sessions: SessionSummary[] }>("/sessions"),

  createSession: (body: { title?: string; session_id?: string }) =>
    request<SessionSummary>("/sessions", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  renameSession: (id: string, title: string) =>
    request<SessionSummary>(`/sessions/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify({ title }),
    }),

  deleteSession: (id: string) =>
    request<{ session_id: string; deleted: boolean }>(
      `/sessions/${encodeURIComponent(id)}`,
      { method: "DELETE" },
    ),

  getMessages: (id: string) =>
    request<{ session_id: string; messages: SessionMessage[] }>(
      `/sessions/${encodeURIComponent(id)}/messages`,
    ),
}
```

`VITE_API_BASE` 從 `.env.development` 讀取，預設 `http://127.0.0.1:8000`。

---

## 7. SSE Parser（`lib/sse.ts`）

`POST /chat/stream` 必須用 `fetch` + `ReadableStream` 自己解。寫一個與框架無關的 parser：

```ts
export interface SseEvent {
  event: string
  data: string
  id?: string
}

export async function* parseSse(
  stream: ReadableStream<Uint8Array>,
  signal?: AbortSignal,
): AsyncGenerator<SseEvent> {
  const decoder = new TextDecoder()
  const reader = stream.getReader()
  let buffer = ""

  try {
    while (true) {
      if (signal?.aborted) return
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      let idx: number
      while ((idx = buffer.indexOf("\n\n")) !== -1) {
        const raw = buffer.slice(0, idx)
        buffer = buffer.slice(idx + 2)
        const evt = parseFrame(raw)
        if (evt) yield evt
      }
    }
  } finally {
    reader.releaseLock()
  }
}

function parseFrame(raw: string): SseEvent | null {
  if (!raw.trim()) return null
  let event = "message"
  const dataLines: string[] = []
  let id: string | undefined
  for (const line of raw.split("\n")) {
    if (line.startsWith(":")) continue            // comment / keepalive
    if (line.startsWith("event:")) event = line.slice(6).trim()
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).replace(/^ /, ""))
    else if (line.startsWith("id:")) id = line.slice(3).trim()
  }
  return { event, data: dataLines.join("\n"), id }
}
```

注意：

- `delta` 事件目前 data 是裸字串，**不要硬 JSON.parse**。
- 其他事件 data 是 JSON，呼叫端再 `JSON.parse`。
- `\n\n` 是 SSE frame 分隔。

---

## 8. 統一錯誤類別（`lib/errors.ts`）

```ts
export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public requestId?: string,
    public status?: number,
  ) {
    super(message)
    this.name = "ApiError"
  }
}
```

UI 層在 toast 顯示時就能拿到 `requestId` 一起秀。

---

## 9. Pinia Stores

### 9.1 `stores/capabilities.ts`

```ts
export const useCapabilitiesStore = defineStore("capabilities", () => {
  const data = ref<Capabilities | null>(null)
  const loaded = ref(false)

  async function load() {
    if (loaded.value) return
    try { data.value = await api.capabilities() } catch { /* fallback */ }
    loaded.value = true
  }

  const toolMap = computed(
    () => new Map(data.value?.tools.map(t => [t.name, t]) ?? []),
  )

  return { data, loaded, load, toolMap }
})
```

### 9.2 `stores/sessions.ts`

```ts
export const useSessionsStore = defineStore("sessions", () => {
  const list = ref<SessionSummary[]>([])
  const loading = ref(false)

  async function fetchAll() {
    loading.value = true
    try {
      const { sessions } = await api.listSessions()
      list.value = sessions.sort(
        (a, b) => b.updated_at.localeCompare(a.updated_at),
      )
    } finally { loading.value = false }
  }

  async function create(title?: string) {
    const created = await api.createSession({ title })
    list.value.unshift(created)
    return created
  }

  async function rename(id: string, title: string) {
    const idx = list.value.findIndex(s => s.session_id === id)
    if (idx < 0) return
    const prev = list.value[idx]!
    list.value[idx] = { ...prev, title }  // 樂觀更新
    try { await api.renameSession(id, title) }
    catch (e) { list.value[idx] = prev; throw e }
  }

  async function remove(id: string) {
    const idx = list.value.findIndex(s => s.session_id === id)
    const prev = list.value[idx]
    list.value.splice(idx, 1)              // 樂觀刪除
    try { await api.deleteSession(id) }
    catch (e) {
      if (prev) list.value.splice(idx, 0, prev)
      throw e
    }
  }

  function touch(id: string, preview: { user: string; assistant: string }) {
    const s = list.value.find(s => s.session_id === id)
    if (!s) return
    s.updated_at = new Date().toISOString()
    s.last_user_message = preview.user
    s.last_assistant_preview = preview.assistant
    s.message_count += 2
    list.value.sort((a, b) => b.updated_at.localeCompare(a.updated_at))
  }

  return { list, loading, fetchAll, create, rename, remove, touch }
})
```

### 9.3 `stores/chat.ts`

每個對話畫面用同一個 store，根據 `currentSessionId` 切換內容。

```ts
export const useChatStore = defineStore("chat", () => {
  const currentSessionId = ref<string | null>(null)
  const messages = ref<DisplayMessage[]>([])
  const streamingMessage = ref<DisplayMessage | null>(null)
  const runStatus = ref<"idle" | "streaming" | "error">("idle")
  const lastError = ref<ApiError | null>(null)
  let abortController: AbortController | null = null

  async function switchTo(id: string | null) {
    abortIfStreaming()
    currentSessionId.value = id
    messages.value = []
    streamingMessage.value = null
    runStatus.value = "idle"
    lastError.value = null
    if (!id) return
    const { messages: history } = await api.getMessages(id)
    messages.value = hydrateHistory(history)
  }

  function abortIfStreaming() {
    if (runStatus.value === "streaming" && abortController) {
      abortController.abort()
      if (streamingMessage.value) {
        streamingMessage.value.status = "aborted"
        messages.value.push(streamingMessage.value)
        streamingMessage.value = null
      }
      runStatus.value = "idle"
    }
  }

  async function send(text: string) {
    if (!currentSessionId.value) return
    if (runStatus.value === "streaming") return
    runStatus.value = "streaming"
    lastError.value = null
    abortController = new AbortController()

    // 樂觀 push user
    messages.value.push({
      id: `local-${Date.now()}`, role: "user", content: text,
      created_at: new Date().toISOString(),
      toolCalls: [], status: "complete",
    })
    streamingMessage.value = {
      id: `local-${Date.now() + 1}`, role: "assistant", content: "",
      created_at: new Date().toISOString(),
      toolCalls: [], status: "streaming",
    }

    try {
      await runStream(
        { session_id: currentSessionId.value, message: text },
        abortController.signal,
        {
          onToolStart: tc => streamingMessage.value!.toolCalls.push(tc),
          onToolFinish: tc => {
            const target = streamingMessage.value!.toolCalls.find(t => t.id === tc.id)
            if (target) Object.assign(target, tc)
          },
          onDelta: t => { streamingMessage.value!.content += t },
          onDone: done => {
            streamingMessage.value!.status = "complete"
            streamingMessage.value!.usage = done.usage
            streamingMessage.value!.toolsUsed = done.tools_used
            messages.value.push(streamingMessage.value!)
            streamingMessage.value = null
          },
        },
      )
    } catch (err) {
      if (err instanceof ApiError) lastError.value = err
      if (streamingMessage.value) {
        streamingMessage.value.status = "error"
        messages.value.push(streamingMessage.value)
        streamingMessage.value = null
      }
    } finally {
      runStatus.value = "idle"
      abortController = null
    }
  }

  function stop() { abortIfStreaming() }

  return {
    currentSessionId, messages, streamingMessage, runStatus, lastError,
    switchTo, send, stop,
  }
})
```

`hydrateHistory()` 與 `runStream()` 抽到 composable（見下節）。

---

## 10. Composables

### 10.1 `composables/useChatStream.ts`

把 SSE 串流邏輯抽出來，store 才不會太胖。

```ts
import { parseSse } from "@/lib/sse"
import { ApiError } from "@/lib/errors"
import type {
  ToolCallStartedData, ToolCallFinishedData, DoneData,
  StreamErrorData, DisplayToolCall,
} from "@/lib/types"

const BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000"

interface Handlers {
  onRunStarted?: () => void
  onToolStart: (tc: DisplayToolCall) => void
  onToolFinish: (tc: Partial<DisplayToolCall> & { id: string }) => void
  onDelta: (text: string) => void
  onDone: (data: DoneData) => void
}

export async function runStream(
  body: { session_id: string; message: string; client_request_id?: string },
  signal: AbortSignal,
  h: Handlers,
) {
  const res = await fetch(`${BASE}/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "Accept": "text/event-stream" },
    body: JSON.stringify(body),
    signal,
  })
  if (!res.ok || !res.body) {
    throw new ApiError("STREAM_FAILED", `HTTP ${res.status}`,
      res.headers.get("X-Request-Id") ?? undefined, res.status)
  }

  for await (const evt of parseSse(res.body, signal)) {
    switch (evt.event) {
      case "run_started":
        h.onRunStarted?.()
        break
      case "tool_call_started": {
        const d = JSON.parse(evt.data) as ToolCallStartedData
        h.onToolStart({
          id: d.id, name: d.name, arguments: d.arguments, status: "running",
        })
        break
      }
      case "tool_call_finished": {
        const d = JSON.parse(evt.data) as ToolCallFinishedData
        h.onToolFinish({
          id: d.id, result: d.result, ok: d.ok,
          status: d.ok ? "ok" : "failed",
        })
        break
      }
      case "delta":
        h.onDelta(evt.data)             // 注意：裸字串
        break
      case "done":
        h.onDone(JSON.parse(evt.data) as DoneData)
        return
      case "error": {
        const d = JSON.parse(evt.data) as StreamErrorData
        throw new ApiError(d.code, d.message, d.request_id)
      }
    }
  }
}
```

### 10.2 `composables/useAutoScroll.ts`

`離底 80px 不強拉` 的規則。

```ts
import { ref, onMounted, onBeforeUnmount } from "vue"

export function useAutoScroll(threshold = 80) {
  const containerRef = ref<HTMLElement | null>(null)
  const pinnedToBottom = ref(true)

  function isNearBottom() {
    const el = containerRef.value
    if (!el) return true
    return el.scrollHeight - el.scrollTop - el.clientHeight < threshold
  }

  function scrollToBottom(behavior: ScrollBehavior = "smooth") {
    const el = containerRef.value
    if (!el) return
    el.scrollTo({ top: el.scrollHeight, behavior })
  }

  function onScroll() { pinnedToBottom.value = isNearBottom() }

  onMounted(() => containerRef.value?.addEventListener("scroll", onScroll))
  onBeforeUnmount(() => containerRef.value?.removeEventListener("scroll", onScroll))

  /** 內容改變時呼叫，會在使用者貼底時自動跟隨 */
  function maintain() {
    if (pinnedToBottom.value) {
      requestAnimationFrame(() => scrollToBottom("auto"))
    }
  }

  return { containerRef, pinnedToBottom, scrollToBottom, maintain }
}
```

### 10.3 `composables/useShortcuts.ts`

全域快捷鍵。組字中（`event.isComposing` 或 `keyCode === 229`）一律不觸發。

### 10.4 `composables/useRelativeTime.ts`

把 ISO 字串轉成「10 分鐘前 / 昨天 / 5/12」。可用 `Intl.RelativeTimeFormat` 自寫或裝 `date-fns`。

---

## 11. Router 設計（`router/index.ts`）

```ts
import { createRouter, createWebHistory } from "vue-router"

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", name: "empty", component: () => import("@/views/EmptyView.vue") },
    {
      path: "/c/:id", name: "chat",
      component: () => import("@/views/ChatView.vue"),
      props: true,
    },
    { path: "/:pathMatch(.*)*", redirect: "/" },
  ],
})
```

在 `ChatView` 內 watch route param，呼叫 `chatStore.switchTo(id)`。

---

## 12. 元件設計

### 12.1 `App.vue`

只負責掛載 `AppShell` + `RouterView` + Toaster：

```vue
<script setup lang="ts">
import AppShell from "@/components/layout/AppShell.vue"
import { Toaster } from "@/components/ui/sonner"
import { onMounted } from "vue"
import { useCapabilitiesStore } from "@/stores/capabilities"
import { useSessionsStore } from "@/stores/sessions"

const caps = useCapabilitiesStore()
const sessions = useSessionsStore()
onMounted(() => { caps.load(); sessions.fetchAll() })
</script>

<template>
  <AppShell>
    <RouterView />
  </AppShell>
  <Toaster richColors closeButton />
</template>
```

### 12.2 `AppShell.vue`

CSS Grid 兩欄：

```vue
<template>
  <div class="grid h-screen w-screen grid-cols-[280px_1fr] bg-background">
    <Sidebar />
    <div class="flex flex-col min-w-0">
      <TopBar />
      <main class="flex-1 min-h-0">
        <slot />
      </main>
    </div>
  </div>
</template>
```

注意 `min-h-0` / `min-w-0`：grid + flex 子項目要顯式設這個才能讓 scroll 容器正確工作。

### 12.3 `Sidebar.vue` / `SessionList.vue` / `SessionItem.vue`

- `Sidebar` 包裝結構：頂部「+ 新對話」按鈕，下面 `<ScrollArea>` 裝 `SessionList`。
- `SessionList` v-for `SessionItem`。
- `SessionItem` props：`session: SessionSummary`、`active: boolean`；emit `select` / `rename` / `delete`。
- 點擊整列 → `router.push(\`/c/\${id}\`)`。
- 右側三點選單用 `DropdownMenu`，「重新命名 / 刪除」兩項。
- 重新命名用內嵌 `<Input>`，按 Enter 觸發 `sessionsStore.rename`。
- 刪除前用 `<Dialog>` 二次確認。

「+ 新對話」實作建議：

```ts
async function newChat() {
  // 方案 A：先建立 session 再導頁
  const s = await sessions.create()
  router.push(`/c/${s.session_id}`)
}
```

如果想做「延遲建立」，可以先 `router.push('/c/new')` 進空白頁，使用者送第一則訊息時才 `await sessions.create()` 拿到真實 id，再 `router.replace(\`/c/\${id}\`)`。

### 12.4 `TopBar.vue`

- 左側：當前 session title（點擊可 in-place 改名，重用 SessionItem 的 rename 機制）
- 右側：模型名稱（從 `capabilitiesStore.data.model.name`）、設定按鈕

### 12.5 `ChatView.vue`

```vue
<script setup lang="ts">
import { watch } from "vue"
import { useChatStore } from "@/stores/chat"

const props = defineProps<{ id: string }>()
const chat = useChatStore()

watch(() => props.id, (id) => chat.switchTo(id), { immediate: true })
</script>

<template>
  <div class="flex flex-col h-full">
    <MessageList class="flex-1 min-h-0" />
    <Composer class="border-t" />
  </div>
</template>
```

### 12.6 `MessageList.vue`

核心職責：渲染歷史 + streamingMessage、處理自動滾動。

```vue
<script setup lang="ts">
import { useChatStore } from "@/stores/chat"
import { useAutoScroll } from "@/composables/useAutoScroll"
import { watch, computed } from "vue"

const chat = useChatStore()
const { containerRef, pinnedToBottom, scrollToBottom, maintain } = useAutoScroll()

const items = computed(() =>
  chat.streamingMessage ? [...chat.messages, chat.streamingMessage] : chat.messages,
)

watch(() => chat.streamingMessage?.content, maintain)
watch(() => chat.messages.length, maintain)
</script>

<template>
  <div ref="containerRef" class="overflow-y-auto px-6 py-4 space-y-4">
    <template v-for="m in items" :key="m.id">
      <UserMessage v-if="m.role === 'user'" :message="m" />
      <AssistantMessage v-else :message="m" />
    </template>
    <EmptyState v-if="items.length === 0" />
    <ScrollToBottom
      v-show="!pinnedToBottom"
      class="absolute right-6 bottom-24"
      @click="scrollToBottom()"
    />
  </div>
</template>
```

### 12.7 `AssistantMessage.vue`

```vue
<script setup lang="ts">
import type { DisplayMessage } from "@/lib/types"
import ToolCallCard from "./ToolCallCard.vue"
import MarkdownView from "../common/MarkdownView.vue"
import StreamingCursor from "./StreamingCursor.vue"
const props = defineProps<{ message: DisplayMessage }>()
</script>

<template>
  <div class="flex gap-3">
    <Avatar><!-- AI icon --></Avatar>
    <div class="flex-1 min-w-0 space-y-2">
      <ToolCallCard
        v-for="tc in message.toolCalls"
        :key="tc.id"
        :tool-call="tc"
      />
      <MarkdownView :content="message.content" />
      <StreamingCursor v-if="message.status === 'streaming'" />
      <div
        v-if="message.status === 'aborted'"
        class="text-xs text-muted-foreground italic"
      >
        已中止（後端可能仍在處理）
      </div>
    </div>
  </div>
</template>
```

### 12.8 `ToolCallCard.vue`

用 shadcn `Collapsible`：

```vue
<script setup lang="ts">
import { Collapsible, CollapsibleContent, CollapsibleTrigger }
  from "@/components/ui/collapsible"
import { Badge } from "@/components/ui/badge"
import { useCapabilitiesStore } from "@/stores/capabilities"
import { Loader2, Check, X, ChevronDown } from "lucide-vue-next"
import { computed } from "vue"
import type { DisplayToolCall } from "@/lib/types"

const props = defineProps<{ toolCall: DisplayToolCall }>()
const caps = useCapabilitiesStore()
const meta = computed(() => caps.toolMap.get(props.toolCall.name))
</script>

<template>
  <Collapsible class="rounded-md border bg-muted/30 text-sm">
    <CollapsibleTrigger class="flex w-full items-center gap-2 px-3 py-2">
      <Loader2 v-if="toolCall.status === 'running'" class="size-4 animate-spin" />
      <Check v-else-if="toolCall.status === 'ok'" class="size-4 text-emerald-500" />
      <X v-else class="size-4 text-red-500" />
      <span class="font-mono">{{ toolCall.name }}</span>
      <Badge v-if="meta?.dangerous" variant="destructive">危險</Badge>
      <ChevronDown class="ml-auto size-4" />
    </CollapsibleTrigger>
    <CollapsibleContent class="border-t px-3 py-2 space-y-2">
      <div>
        <div class="text-xs text-muted-foreground">Arguments</div>
        <pre class="text-xs whitespace-pre-wrap break-words">{{ JSON.stringify(toolCall.arguments, null, 2) }}</pre>
      </div>
      <div v-if="toolCall.result !== undefined">
        <div class="text-xs text-muted-foreground">Result</div>
        <pre class="text-xs whitespace-pre-wrap break-words max-h-80 overflow-auto">{{ formatResult(toolCall.result) }}</pre>
      </div>
    </CollapsibleContent>
  </Collapsible>
</template>

<script lang="ts">
function formatResult(r: unknown): string {
  if (typeof r === "string") return r
  return JSON.stringify(r, null, 2)
}
</script>
```

### 12.9 `Composer.vue`

```vue
<script setup lang="ts">
import { ref, computed } from "vue"
import { Textarea } from "@/components/ui/textarea"
import { Button } from "@/components/ui/button"
import { Send, Square } from "lucide-vue-next"
import { useChatStore } from "@/stores/chat"

const chat = useChatStore()
const text = ref("")
const isComposing = ref(false)

const canSend = computed(() =>
  text.value.trim().length > 0 &&
  chat.runStatus !== "streaming" &&
  chat.currentSessionId !== null,
)

function send() {
  if (!canSend.value) return
  const t = text.value
  text.value = ""
  chat.send(t)
}

function onKeydown(e: KeyboardEvent) {
  if (isComposing.value || e.keyCode === 229) return
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault()
    if (chat.runStatus === "streaming") return
    send()
  }
  if (e.key === "Escape") {
    if (chat.runStatus === "streaming") chat.stop()
    else text.value = ""
  }
}
</script>

<template>
  <div class="p-4">
    <div class="relative rounded-xl border bg-background">
      <Textarea
        v-model="text"
        rows="1"
        placeholder="輸入訊息..."
        class="resize-none border-0 pr-12 max-h-48"
        @keydown="onKeydown"
        @compositionstart="isComposing = true"
        @compositionend="isComposing = false"
      />
      <Button
        v-if="chat.runStatus !== 'streaming'"
        size="icon"
        class="absolute right-2 bottom-2"
        :disabled="!canSend"
        @click="send"
      >
        <Send class="size-4" />
      </Button>
      <Button
        v-else
        size="icon"
        variant="destructive"
        class="absolute right-2 bottom-2"
        @click="chat.stop"
      >
        <Square class="size-4" />
      </Button>
    </div>
  </div>
</template>
```

### 12.10 `MarkdownView.vue`

建議用 `markdown-it` + `markdown-it-highlightjs` + `DOMPurify`：

```bash
npm i markdown-it markdown-it-highlightjs highlight.js dompurify
npm i -D @types/markdown-it @types/dompurify
```

```vue
<script setup lang="ts">
import { computed } from "vue"
import MarkdownIt from "markdown-it"
import hljsPlugin from "markdown-it-highlightjs"
import DOMPurify from "dompurify"
import "highlight.js/styles/github-dark.css"

const md = new MarkdownIt({ linkify: true, breaks: true })
  .use(hljsPlugin, { auto: true, code: true })

const props = defineProps<{ content: string }>()
const html = computed(() => DOMPurify.sanitize(md.render(props.content)))
</script>

<template>
  <div class="prose prose-sm dark:prose-invert max-w-none" v-html="html" />
</template>
```

Streaming 時 `content` 會頻繁變化，`computed` 已自帶 cache，但若仍嫌卡：用 `customRef` 加 50ms 節流。

### 12.11 `Toast` / 錯誤呈現

用 shadcn-vue 的 `sonner`。在 `chat.send` 的 catch 內：

```ts
import { toast } from "vue-sonner"
toast.error(err.message, { description: err.requestId })
```

在 `App.vue` 內掛 `<Toaster />` 一次即可。

---

## 13. 開發環境變數

`frontend/.env.development`：

```
VITE_API_BASE=http://127.0.0.1:8000
```

Vite dev server 預設 `5173`，後端 `8000`。**CORS 必須在後端 FastAPI 開**，否則瀏覽器直連會被擋（這是後端要補的，不在前端範圍）。短期 workaround：在 `vite.config.ts` 加 proxy：

```ts
server: {
  proxy: {
    "/chat": "http://127.0.0.1:8000",
    "/sessions": "http://127.0.0.1:8000",
    "/capabilities": "http://127.0.0.1:8000",
    "/health": "http://127.0.0.1:8000",
  },
},
```

然後 `VITE_API_BASE` 留空字串，請求走相對路徑 → 走 vite proxy → 沒有 CORS 問題。

---

## 14. 建議建置順序（incremental）

按以下順序做，每步都能在瀏覽器看到東西：

### Wave 1：能跑通空殼

1. 寫 `lib/types.ts` + `lib/api.ts` + `lib/errors.ts`
2. 安裝 shadcn 元件：button, textarea, scroll-area, dropdown-menu, dialog, sonner, skeleton, collapsible, badge
3. 寫 `AppShell` + `Sidebar` + `TopBar`（先用 mock data）
4. router 設好 `/` 與 `/c/:id`，建立 `EmptyView` / `ChatView` placeholder
5. 串 `useCapabilitiesStore.load()` 確認後端通

### Wave 2：對話列表能動

6. 串 `useSessionsStore.fetchAll()`，sidebar 渲染真實資料
7. 實作「新對話」按鈕（先選方案 A：立即建立）
8. 實作 rename / delete（含 Dialog 確認）
9. 點對話切換到 `/c/:id`，TopBar 顯示 title

### Wave 3：訊息列表能讀

10. `ChatView` watch route，呼叫 `chatStore.switchTo(id)`
11. 寫 `MessageList` + `UserMessage` + `AssistantMessage` + `MarkdownView`
12. 寫 `useAutoScroll`，先確認靜態歷史能載入並顯示

### Wave 4：能聊天（非串流）

13. 寫 `Composer.vue`，先接 `POST /chat`（同步版）試水溫
14. 確認 user 樂觀渲染 + assistant 回覆能正確 append

### Wave 5：SSE 串流

15. 寫 `lib/sse.ts`、`composables/useChatStream.ts`
16. `chatStore.send` 切到 `POST /chat/stream`
17. 寫 `StreamingCursor`、`ToolCallCard`，把 delta / tool call 視覺化做出來
18. 實作 stop 按鈕（abort fetch）

### Wave 6：細節打磨

19. ScrollToBottom 浮動按鈕
20. Sonner toast 統一錯誤
21. ConnectionBanner（health 失敗）
22. 快捷鍵 composables
23. 暗色模式 toggle
24. 開發者模式

每個 Wave 結束都應該是「可以 demo 給人看」的狀態。

---

## 15. 容易踩到的坑

| 坑 | 怎麼避 |
| --- | --- |
| Tailwind v4 沒套用 | 確認 `vite.config.ts` 有 `@tailwindcss/vite`，CSS 入口用 `@import "tailwindcss"`（不是 v3 的 `@tailwind` 指令） |
| ScrollArea 拿不到原生 scroll 事件 | shadcn 的 `<ScrollArea>` 內部結構不同；自動滾動建議用原生 `<div class="overflow-y-auto">` 或設好 viewport ref |
| `noUncheckedIndexedAccess` 抱怨 | `arr[idx]` 是 `T \| undefined`，要先判空或加 `!`，store 範例已展示 |
| `<Textarea>` 自動高度 | shadcn 的 textarea 不會自己長高；可加 `auto-resize` directive 監聽 input 改 `style.height` |
| Markdown 串流不閉合 | code block 中途三反引號還沒到時，整段都會被當成 code；可以接受，或在 stream 中做 lightweight 預處理（補閉合） |
| EventSource 不支援 POST | 已避開：本文件全程用 fetch + ReadableStream |
| 中文輸入法 Enter 誤送 | Composer 範例已用 `compositionstart/end` + `keyCode === 229` 雙重保護 |
| 切換 session 時舊 stream 沒中斷 | `chatStore.switchTo` 第一行先 `abortIfStreaming()` |
| Sidebar 在 streaming 時刪除目前對話 | `remove` 之前先 abort、再切到下一個 session（路由 push） |
| CORS | 後端要開 `CORSMiddleware`，或用 vite proxy 暫時避開 |

---

## 16. 後續可擴充點

當前文件覆蓋的是基本聊天能力。下列等 API 後端補齊再做：

- **Abort 真正生效**：後端加 `POST /chat/abort` 後，`chatStore.stop()` 多打一次 abort endpoint
- **Workspace 檔案瀏覽**：右側可加第三欄 `WorkspacePanel.vue`，串 `GET /sessions/{id}/workspace/tree`
- **Regenerate**：每則 assistant 訊息 hover 顯示按鈕，呼叫 `POST /sessions/{id}/messages/{msg_id}/regenerate`
- **多模態**：Composer 加 attachment 上傳區
- **命令面板**：用 `<Command>` 元件做 Cmd+K

---

## 17. 一句話總結

- **`lib/`** 是與框架無關的底層（API、SSE、types、errors）
- **`stores/`** 是應用層狀態（capabilities、sessions、chat）
- **`composables/`** 是元件可重用邏輯（auto scroll、shortcuts、chat stream）
- **`components/`** 只負責渲染與接事件，狀態都從 store 拿

照這個分層走，元件會薄、邏輯可測、未來重構成 React / Solid 也只需要重寫最外層。
