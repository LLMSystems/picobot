# Picobot 前端功能補充文檔

## 0. 文件目的

這份文件是 [frontend_vue_implementation.md](frontend_vue_implementation.md) 的延伸補充，記錄**Wave 1–6 主聊天介面完工之後**才加進來的進階功能。

每個功能會獨立切一節，內含：

- 功能定位（為什麼要做）
- UX 設計重點
- 後端 API 對應
- 前端實作計畫（state / 元件 / 整合點 / 建置順序）
- 容易踩到的坑

目前涵蓋：

- [§1 WorkspacePanel](#1-workspacepanel)

未來功能（regenerate、檔案上傳、命令面板等）會以同樣結構新增章節。

對應的：

- 後端 API 細節：[frontend_api_reference.md](frontend_api_reference.md)
- 整體互動規格：[frontend_interaction_spec.md](frontend_interaction_spec.md)
- 主介面實作：[frontend_vue_implementation.md](frontend_vue_implementation.md)

---

## 1. WorkspacePanel

### 1.1 功能定位

picobot 為每個 session 配一個獨立的 workspace 目錄。agent 透過 `read_file` / `write_file` / `edit_file` / `exec` 等工具讀寫的就是這個目錄。WorkspacePanel 的職責：

- 讓使用者**看見**目前 session workspace 裡有哪些檔案
- 讓使用者**預覽**檔案內容（文字檔）
- agent 寫檔之後**自動刷新**，給「正在生長中的工作目錄」感覺

第一版定位是**read-only file explorer**，不提供前端寫入 / 刪除 / 上傳。

### 1.2 整體版面變化（2 → 3 欄）

原本版面（Wave 1）：

```
┌──────────┬──────────────────────────────┐
│          │  TopBar                       │
│ Sidebar  ├──────────────────────────────┤
│          │  MessageList                  │
│          │                               │
│          ├──────────────────────────────┤
│          │  Composer                     │
└──────────┴──────────────────────────────┘
```

新版面：

```
┌──────────┬───────────────────┬──────────────────┐
│          │  TopBar           │                   │
│ Sidebar  ├───────────────────┤  WorkspacePanel  │
│          │  MessageList       │   ├ FileTree    │
│          │                    │   └ FilePreview │
│          ├───────────────────┤                   │
│          │  Composer         │                   │
└──────────┴───────────────────┴──────────────────┘
```

要點：

- TopBar 加一個切換按鈕（icon `PanelRight` / `FolderTree`），收合 / 展開 WorkspacePanel
- WorkspacePanel 預設**展開**（如果 `capabilities.features.session_workspace === true`）
- 若 capability 為 `false`，整個 panel 與切換按鈕都隱藏

### 1.3 響應式

- **桌面寬度（≥ 1280px）**：三欄並排
- **平板（768 ~ 1279px）**：WorkspacePanel 預設**收合**；使用者主動展開時以 overlay 覆蓋在 MessageList 上
- **手機（< 768px）**：WorkspacePanel 改為全螢幕 modal，從右側滑入

### 1.4 應用層狀態

新增一個 store：`stores/workspace.ts`。

```ts
interface WorkspaceState {
  // 當前 session 的 tree（扁平結構，由 path 為 key）
  entries: Map<string, WorkspaceEntry>
  // 已展開的目錄路徑集合（lazy load）
  expanded: Set<string>
  // 目前被選中要預覽的檔案
  selectedPath: string | null
  // 預覽內容
  fileContent: FileContent | null
  // 載入狀態
  loadingTree: boolean
  loadingFile: boolean
  // UI 切換
  visible: boolean
  // 最後一次成功刷新的時間（給 "剛剛更新" hint 用）
  lastSyncedAt: number
}

interface WorkspaceEntry {
  path: string         // 相對 workspace 的完整路徑
  name: string
  type: 'file' | 'directory'
  size: number | null
  updated_at: string
  // 此 entry 是否為頂層或某個展開目錄的子節點
  parent: string       // 父目錄 path，根層為 ''
  // 對 directory 而言：是否已 load 過子節點
  childrenLoaded?: boolean
}
```

選擇用 `Map<path, entry>` 而不是巢狀樹，是因為：

- 局部刷新（`workspace_changed.paths`）時直接用 path 命中、O(1) 更新
- 樹狀渲染從 entries 過濾 `parent === currentDir` 即可
- 排序、過濾都好寫

### 1.5 元件結構

新增檔案：

```
src/components/workspace/
├── WorkspacePanel.vue        # 整個第三欄
├── WorkspaceTree.vue         # 樹狀容器
├── WorkspaceTreeNode.vue     # 單一節點（file 或 folder）
├── WorkspaceFilePreview.vue  # 右半部檔案預覽
├── WorkspaceEmpty.vue        # 空狀態 / 錯誤狀態
└── WorkspaceHeader.vue       # 標題列 + 排序 / 刷新按鈕
```

`WorkspacePanel.vue` 結構：

```vue
<template>
  <aside v-if="caps.featureWorkspace && ws.visible" class="...">
    <WorkspaceHeader />
    <div class="grid grid-rows-[1fr_1fr] min-h-0">
      <WorkspaceTree />
      <WorkspaceFilePreview />
    </div>
  </aside>
</template>
```

上下兩段；之後可以視 UX 改成左右兩欄、或 tabs 切換。

### 1.6 API 層擴充

在既有 `lib/api.ts` 加兩個方法：

```ts
listWorkspaceTree: (
  id: string,
  params?: { path?: string; recursive?: boolean; max_entries?: number },
) =>
  request<WorkspaceTreeResponse>(
    `/sessions/${encodeURIComponent(id)}/workspace/tree?${qs(params)}`,
  ),

readWorkspaceFile: (
  id: string,
  params: { path: string; offset?: number; limit?: number },
) =>
  request<WorkspaceFileResponse>(
    `/sessions/${encodeURIComponent(id)}/workspace/file?${qs(params)}`,
  ),
```

對應 type 加在 `lib/types.ts`：

```ts
export interface WorkspaceEntryDTO {
  path: string
  name: string
  type: 'file' | 'directory'
  size: number | null
  updated_at: string
}

export interface WorkspaceTreeResponse {
  session_id: string
  path: string
  entries: WorkspaceEntryDTO[]
  truncated: boolean
}

export interface WorkspaceFileResponse {
  session_id: string
  path: string
  content: string
  encoding: string
  truncated: boolean
  line_count: number
}

export interface WorkspaceChangedData {
  session_id: string
  paths: string[]
}
```

### 1.7 SSE 事件整合

`composables/useChatStream.ts` 已有 switch case 處理 `run_started` / `tool_call_started` / `tool_call_finished` / `delta` / `done` / `error`。增加一個 case：

```ts
case 'workspace_changed': {
  const d = JSON.parse(evt.data) as WorkspaceChangedData
  h.onWorkspaceChanged?.(d)
  break
}
```

`stores/chat.ts` 內 `send()` 傳遞 handler 給 chat stream：

```ts
onWorkspaceChanged: (d) => {
  const ws = useWorkspaceStore()
  if (d.paths.length === 0) {
    void ws.refreshTree()
  } else {
    void ws.refreshPaths(d.paths)
  }
}
```

**對 `POST /chat` 非串流路徑**：response `events[]` 也會帶 `workspace_changed`，在 `chat.ts` 走完非串流分支後掃一遍 events 做同樣處理。

### 1.8 互動細節

**載入**

- 切換 session（`chatStore.switchTo`）後，`workspaceStore.bind(sessionId)` 同步觸發：清空舊狀態 → 呼叫 `listWorkspaceTree({ path: '.', recursive: false })`
- 如果 `WORKSPACE_NOT_AVAILABLE` → 顯示 EmptyState「此 session 無 workspace」
- 如果回來是空 → 顯示「workspace 為空，等 agent 開始建立檔案」

**展開目錄**

- 點目錄左邊的箭頭 → 加入 `expanded` Set；若 `childrenLoaded` 為 false 才呼叫 API 抓 `tree?path=foo`
- 點目錄名本身視為「展開 / 收合」二合一

**預覽檔案**

- 點檔案 → `selectedPath = path`，呼叫 `readWorkspaceFile({ path })`
- 對 markdown（`.md` / `.markdown`） → 用既有 [MarkdownView.vue](frontend/src/components/common/MarkdownView.vue) 渲染
- 其他文字檔 → 顯示 `<pre><code>` + highlight.js 語法上色（用副檔名映射）
- 拿到 `WORKSPACE_BINARY_FILE_UNSUPPORTED` → 顯示「此檔為 binary，無法預覽」，給檔案大小資訊
- 拿到 `truncated: true` → 預覽下方顯示「已截斷，前 N 行」+「載入更多」按鈕，點擊後 `offset = lastLine`、`limit = 2000` 追加

**排序**

- WorkspaceHeader 提供兩種排序：
  - **依修改時間（預設）**：`updated_at` 降冪，加上 directory-first
  - **依名稱**：字母 / 數字升冪，加上 directory-first
- 排序狀態存在 store，session 切換時保留

**workspace_changed 自動刷新**

- 收到事件 → 更新 `lastSyncedAt`，依規則：
  - `paths` 為空 → 重抓**所有已展開**的目錄（不要遞迴抓整個 workspace 否則太重）；若目前預覽中的檔案在這些路徑下，也重抓檔案
  - `paths` 非空 → 對每個 path：
    - 若 path 屬於已展開的目錄 → 重抓該目錄
    - 若 path === selectedPath → 重抓檔案
    - 否則只更新 entry 的 `updated_at` / `size`
- 連續多個 `workspace_changed` 事件 → debounce 250ms，避免每個 delta 都打 API

**手動刷新**

- WorkspaceHeader 右上角放一個 `RefreshCw` icon 按鈕，點擊強制重抓整棵已展開的樹

### 1.9 Edge cases

| 情境 | 預期行為 |
| --- | --- |
| `capabilities.features.session_workspace === false` | 整個 panel 與 toggle 按鈕都隱藏 |
| Session 是剛建立的、workspace 還沒實際建立目錄 | 顯示 EmptyState「workspace 為空」 |
| 預覽中的檔案被 agent 改動 | 拿 `workspace_changed.paths` 命中時，**保留捲動位置** 重抓內容並 patch in |
| 預覽中的檔案被 agent 刪除 | `readWorkspaceFile` 回 `WORKSPACE_FILE_NOT_FOUND` → 顯示「此檔案已不存在」並清空 selectedPath |
| 同時開了多個 chat tab（瀏覽器分頁） | 各分頁獨立發 SSE，各自收到 `workspace_changed`，各自刷新自己看到的狀態 |
| `tree` 回 `truncated: true` | 在該目錄底下顯示「已截斷，可能還有檔案沒列出」提示；不自動翻頁（避免一次拉爆） |
| 預覽超大檔（line_count > 10k） | 預設只抓前 2000 行；UI 顯示行數總計 + 「載入更多」 |
| WorkspacePanel 收合狀態下收到 `workspace_changed` | 仍更新 store；下次展開時直接看到最新狀態，不重抓 |
| 切換 session 時上一個 session 的 file fetch 還在路上 | 用 `currentSessionId` 比對；late response 丟棄 |

### 1.10 建置順序

**Wave W1：能渲染樹**

1. 加 types（`WorkspaceEntryDTO` / `WorkspaceTreeResponse` 等）
2. 加 `api.listWorkspaceTree` / `api.readWorkspaceFile`
3. 建 `stores/workspace.ts` 含 `bind` / `refreshTree` / lazy load
4. 改 `AppShell.vue`，加入 `<WorkspacePanel>` 為第三欄
5. 寫 `WorkspacePanel` + `WorkspaceHeader` + `WorkspaceTree` + `WorkspaceTreeNode`（顯示 + 展開 / 收合 + lazy load）

**Wave W2：能預覽檔案**

6. 寫 `WorkspaceFilePreview`（依副檔名分流：md / text / binary）
7. 接 markdown 渲染（重用 [MarkdownView.vue](frontend/src/components/common/MarkdownView.vue)）
8. 接 highlight.js code preview
9. binary / 找不到檔 / 超大檔 truncated 的提示

**Wave W3：自動刷新**

10. 擴 `useChatStream` 加 `workspace_changed` case
11. `chat.ts` 串到 `workspaceStore.refreshTree` / `refreshPaths`
12. 加 debounce
13. `POST /chat` 路徑也掃 `events[]` 做同樣事

**Wave W4：UX 打磨**

14. 排序切換（時間 / 名稱）
15. 手動刷新按鈕
16. Toggle 收合，桌面 / 平板 / 手機響應式
17. 「剛剛更新」徽章（hover entry 顯示 `updated_at` 相對時間）
18. 預覽載入更多（offset / limit 追加）
19. 鍵盤快捷鍵：`Cmd/Ctrl + B` 切換 panel

每個 Wave 結束都應該是「可以 demo 給人看」的狀態，跟主介面的 Wave 切分原則一致。

### 1.11 容易踩到的坑

| 坑 | 怎麼避 |
| --- | --- |
| `workspace_changed` 在每個 SSE delta 之間擠來擠去，連續打 N 次 API | 250ms debounce + 合併 `paths` |
| Tree 用巢狀資料結構，局部刷新很難寫 | 採用 `Map<path, entry>` 扁平結構，渲染端用 computed 重組 |
| 點目錄展開時把已存在的子節點蓋掉 | `refreshPaths(['foo/'])` 只 patch / merge，不整個取代陣列 |
| Late response 把舊 session 的 tree 蓋到新 session 上 | 每個 API 呼叫帶當下 `sessionId`，回來時比對 `chatStore.currentSessionId` |
| 預覽中的檔案被刪 → UI 卡在 loading | 在 fetch 的 catch 內處理 `WORKSPACE_FILE_NOT_FOUND` |
| 大檔 `readWorkspaceFile` 沒設 `limit` → response 幾百 KB | 預設帶 `limit: 2000`，需要時讓使用者按「載入更多」 |
| 切 session 時 panel scroll 沒重置，看起來像「停留在上一個 session 的位置」 | `bind(sessionId)` 內呼叫 `WorkspaceTree` 與 `WorkspaceFilePreview` 暴露的 `resetScroll()` |
| Toggle panel 沒記住使用者偏好 | `visible` 寫入 `localStorage`，跟 [useTheme.ts](frontend/src/composables/useTheme.ts) 同套路 |
| 預覽 markdown 時 mermaid 區塊內部 svg id 撞到聊天視窗的 svg id | [MarkdownView.vue](frontend/src/components/common/MarkdownView.vue) 已用 module-level counter，重用就不會撞 |

---

## 2. 未來補充（保留位）

待之後設計時再展開：

- **Regenerate 訊息**：每則 assistant 訊息加 `regenerate` 按鈕，呼叫 `POST /sessions/{id}/messages/{msg_id}/regenerate`（後端尚未提供）
- **檔案上傳**：等 `features.file_upload` 為 true、後端開 `POST /sessions/{id}/workspace/file`
- **Workspace 寫入 / 刪除**：等對應後端 API
- **Cmd+K 命令面板**：跨 session 搜尋、快速跳轉、執行常用命令
- **多模態輸入**：等 `features.multimodal` 為 true
