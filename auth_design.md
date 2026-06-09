# 登入 / 多使用者隔離（Auth）設計文檔

> 分支：`feat/auth-login`
> 狀態：設計階段（尚未實作）
> 目標讀者：picobot 維護者

---

## 1. 背景與目標

目前 picobot **完全沒有任何認證**，且 session 是「全域共享」的：

- [app.py](simplified_chatbot/server/app.py) 掛了 9 個 router，沒有一條受保護。
- [endpoints_sessions.py:34](simplified_chatbot/server/endpoints_sessions.py#L34) 的 `GET /sessions` 直接回傳**所有人**的 session，不分使用者。
- DB（[session_store.py](simplified_chatbot/runtime/session_store.py)）的 `session_metadata` / `session_messages` / `subagent_runs` 等表**沒有 `user_id` 欄位**。

**目標**：

1. 使用者可**註冊 / 登入 / 登出**。
2. 登入後**只看得到、只能操作自己的 session 與 workspace**（多使用者隔離）。
3. 未登入者無法存取受保護的 API；前端未登入自動導向登入頁。

**已拍板的設計決定**（見 §3）：

| 決定 | 選擇 |
|------|------|
| 隔離程度 | **多使用者隔離**（session 綁 user） |
| 憑證機制 | **httpOnly cookie session**（簽名 cookie） |
| 註冊 | **開放使用者自行註冊** |

**非目標（本次不做）**：

- 不做 OAuth / 第三方登入（Google 等）。
- 不做角色權限（RBAC）/ admin 後台 / 多租戶組織。
- 不做 email 驗證、忘記密碼流程（預留欄位，後續再補）。
- 既有「全域 / 無主」session 不做資料搬遷，視為 legacy（見 §6.3）。

---

## 2. 現況分析：要動哪些地方

| 綁死點 | 位置 | 說明 |
|--------|------|------|
| 沒有 user 概念 | 全 repo | DB、runtime、API、前端都沒有使用者 |
| session 全域可見 | [endpoints_sessions.py:34-42](simplified_chatbot/server/endpoints_sessions.py#L34-L42) | `list_sessions` 不過濾；任何人拿到 `session_id` 就能讀 |
| session metadata 無 user | [session_store.py:375](simplified_chatbot/runtime/session_store.py#L375) | 只有 `session_id / created_at / updated_at / title` |
| runtime 方法無 user 維度 | [local_runtime.py](simplified_chatbot/runtime/local_runtime.py) `list_session_summaries_async` / `create_session_async` / `get_session_summary_async` / `reset/rename` | 簽名都沒有 `user_id` |
| 前端無 auth | [router/index.ts](frontend/src/router/index.ts)、[api.ts:54](frontend/src/lib/api.ts#L54) | 沒有 guard，`request()` 不帶憑證 |
| EventSource 不能帶 header | [subagents.ts:475](frontend/src/stores/subagents.ts#L475)、[metrics.ts:135](frontend/src/stores/metrics.ts#L135)、[alerts.ts:167](frontend/src/stores/alerts.ts#L167) | **這是選 cookie 而非 Bearer 的關鍵原因** |

**好消息**：

- CORS 已經是 `allow_credentials=True`（[app.py:118-125](simplified_chatbot/server/app.py#L118-L125)），cookie 幾乎不用改 CORS。
- `session_metadata` 已有「`ALTER TABLE ... ADD COLUMN`」的 migration idiom（[session_store.py:383-389](simplified_chatbot/runtime/session_store.py#L383-L389)），加 `user_id` 可沿用、不需砍 DB。
- 端點層已有統一的 `error_response` 與 `get_runtime` 依賴（[common.py](simplified_chatbot/server/common.py)），新增 `get_current_user` 依賴可比照。

---

## 3. 為什麼是 cookie session（而非 JWT Bearer）

前端串流分兩種：

| 串流 | 方式 | 能帶自訂 header？ |
|------|------|------------------|
| `/chat/stream` | `fetch`（[useChatStream.ts:30](frontend/src/composables/useChatStream.ts#L30)） | ✅ |
| metrics / alerts / subagent events | **`EventSource`** | ❌（瀏覽器 API 限制） |

`EventSource` 無法加 `Authorization` header。若走 Bearer，這三條 SSE 只能把 token 塞 query string → 會被 access log / proxy 記錄，是安全瑕疵。

**cookie session** 則：

- `EventSource` 只要 `withCredentials: true` 就自動帶 cookie。
- httpOnly cookie 前端 JS 讀不到，天然防 XSS 竊取。
- 代價是 CSRF，靠 `SameSite=Lax` + 狀態變更只走 POST 即可緩解（§7）。

---

## 4. 認證機制細節

### 4.1 Cookie session

- 用 Starlette 內建 `SessionMiddleware`（簽名 cookie，底層 itsdangerous），不需要額外 server-side session 表。
- Cookie 屬性：`httponly=True`、`samesite="lax"`、`secure`（部署 HTTPS 時為 True，本機 dev 為 False，由設定控制）。
- Cookie 內容只放 `{"user_id": <int>}`（簽名防竄改，不放密碼/敏感資料）。
- Secret 從環境變數 `SESSION_SECRET` 讀；未設定時 server 啟動失敗或產生臨時 secret（dev 用，會警告）。

### 4.2 密碼雜湊

- 使用 `argon2-cffi`（`argon2.PasswordHasher`），預設參數即可。
- 只存 `password_hash`，永不存明碼。
- 驗證失敗（使用者不存在 / 密碼錯）一律回相同錯誤訊息，避免帳號列舉。

### 4.3 新增依賴

`pyproject.toml` 加入：

```
"argon2-cffi>=23.1.0",
"itsdangerous>=2.0.0",   # SessionMiddleware 簽名所需（Starlette 用）
```

---

## 5. 資料模型

### 5.1 新增 `users` 表

```sql
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL
);
```

- `username` 大小寫不敏感唯一（存小寫正規化值，或建 `UNIQUE` index on `lower(username)`）。
- 預留 `email` 欄位視需要後補（本次不做）。

### 5.2 `session_metadata` 加 `user_id`

沿用既有 migration idiom：

```python
if "user_id" not in columns:
    conn.execute("ALTER TABLE session_metadata ADD COLUMN user_id INTEGER")
```

- 既有 row 的 `user_id` 為 `NULL` → 視為 legacy / 無主 session（見 §6.3）。
- 加 index：`CREATE INDEX IF NOT EXISTS idx_session_metadata_user ON session_metadata(user_id)`。

### 5.3 隔離邊界

只在 **session 擁有權**這一層做隔離即可達成目標：

- `subagent_runs` / `subagent_events` / `session_messages` / `session_memory` 都以 `session_id` 為 key，**透過 session 的擁有權間接隔離**——只要存取 session 前先驗證 `session.user_id == current_user.id`，子資源就自然受保護。
- workspace 目錄以 `session_id` 命名，同理。

---

## 6. 後端架構

### 6.1 新檔案

| 檔案 | 職責 |
|------|------|
| `simplified_chatbot/auth/__init__.py` | package |
| `simplified_chatbot/auth/users_store.py` | `UsersStore`：建立/查詢 user、雜湊/驗證密碼（AioSQLite，比照 session_store） |
| `simplified_chatbot/auth/passwords.py` | argon2 包裝（`hash_password` / `verify_password`） |
| `simplified_chatbot/server/endpoints_auth.py` | `/auth/*` 路由 |
| `simplified_chatbot/server/deps.py` | `get_current_user` / `require_user` 依賴 |

### 6.2 API

| Method | Path | 說明 | 驗證 |
|--------|------|------|------|
| `POST` | `/auth/register` | `{username, password}` → 建帳號並直接登入（set cookie） | 公開 |
| `POST` | `/auth/login` | `{username, password}` → set cookie | 公開 |
| `POST` | `/auth/logout` | 清 cookie | 任意 |
| `GET`  | `/auth/me` | 回 `{id, username}` 或 401 | 需登入 |

錯誤碼（沿用 `error_response`）：`USERNAME_TAKEN`(409)、`INVALID_CREDENTIALS`(401)、`WEAK_PASSWORD`(422)、`UNAUTHENTICATED`(401)、`SESSION_NOT_FOUND`(404)。

### 6.3 受保護路由與隔離規則

- `get_current_user`：從 cookie 讀 `user_id`，查不到 user → 401（`UNAUTHENTICATED`）。
- 掛載對象：`chat` / `sessions` / `workspace` / `skills` / `mcp` router。`metrics` / `alerts` / `health` 維持公開（營運監控；可後續再保護）。
- **隔離規則**：所有 `/sessions/{id}/...` 端點先取 session summary，若 `session.user_id != current_user.id` → 回 **404**（`SESSION_NOT_FOUND`，不用 403，避免洩漏 session 存在性）。
- **legacy（user_id 為 NULL）session**：預設**只有後端可見、前端列表不顯示**；不自動歸給任何人。`list_sessions` 只回 `user_id == current_user.id` 的 session。

### 6.4 runtime 改動

下列方法新增 `user_id` 參數（往下傳到 store 過濾）：

- `list_session_summaries_async(user_id)` → `WHERE user_id = ?`
- `create_session_async(..., user_id)` → 寫入 `user_id`
- `get_session_summary_async(session_id)` 回傳含 `user_id`，端點層自行比對（store 不做授權，授權留在端點）

> 設計取捨：**授權判斷放端點層**（拿 summary 後比對 user_id），store 維持「資料存取」單一職責，較好測試也不破壞既有呼叫點。

---

## 7. 安全考量

| 項目 | 對策 |
|------|------|
| 密碼外洩 | argon2 雜湊；永不回傳/記錄明碼 |
| Cookie 竊取 | `httponly` + 部署 `secure` |
| CSRF | `samesite="lax"`；狀態變更走 POST/PATCH/DELETE（瀏覽器對跨站非簡單請求會擋）；必要時加 double-submit token（本次先不做，列為後續） |
| 帳號列舉 | login/register 失敗回一致訊息 |
| 暴力破解 | （後續）register/login 加簡易 rate limit |
| 越權存取他人 session | 端點層比對 `user_id`，不符回 404 |
| Cookie 簽章金鑰 | `SESSION_SECRET` 必填；缺少時 dev 警告、prod 應啟動失敗 |

---

## 8. 前端架構

### 8.1 新檔案 / 改動

| 檔案 | 動作 |
|------|------|
| `frontend/src/stores/auth.ts` | 新增：`me` / `login` / `register` / `logout` / `fetchMe` |
| `frontend/src/views/LoginView.vue` | 新增：登入頁 |
| `frontend/src/views/RegisterView.vue` | 新增：註冊頁 |
| `frontend/src/router/index.ts` | 加 `/login`、`/register` route + `beforeEach` guard |
| `frontend/src/lib/api.ts` | `request`/`requestRaw` 加 `credentials: 'include'`；加 `authMe/authLogin/authRegister/authLogout`；401 統一處理 |
| `frontend/src/stores/subagents.ts`、`metrics.ts`、`alerts.ts` | `EventSource` 改 `withCredentials: true` |
| `frontend/src/App.vue` | 啟動先 `fetchMe`，未登入不載 sessions |

### 8.2 流程

1. App 啟動 → `GET /auth/me`。200 → 已登入，照常載入；401 → router guard 導向 `/login`。
2. 登入/註冊成功 → cookie 已 set → 重新 `fetchMe` → 導回首頁。
3. 任意 API 回 401 → 清 auth store → 導向 `/login`。
4. 登出 → `POST /auth/logout` → 清狀態 → `/login`。

### 8.3 EventSource 注意

三條 `EventSource` 必須改 `withCredentials: true`，否則會出現「頁面能開但串流靜默失敗」。這是本次最容易漏的點。

---

## 9. 分階段實作計畫

每個 phase 都可獨立 commit + 跑測試。

### Phase 1 — Users 與 Auth 端點（無隔離）

- `auth/passwords.py`、`auth/users_store.py`、`endpoints_auth.py`、`deps.py`。
- 加依賴、`SessionMiddleware`、`SESSION_SECRET` 設定。
- **測試** `tests/test_auth_endpoints.py`：
  - register 成功 → 200 + set cookie + `/auth/me` 回該 user
  - 重複 username → 409
  - 弱密碼 → 422
  - login 正確/錯誤密碼 → 200 / 401（訊息一致）
  - logout 後 `/auth/me` → 401
  - 密碼雜湊 round-trip（`passwords.py` 單元測試）

### Phase 2 — 路由保護（cookie → user）

- `get_current_user` 掛上 chat / sessions / workspace / skills / mcp router。
- **測試** `tests/test_auth_protected_routes.py`：
  - 未帶 cookie 打 `/sessions` → 401
  - 帶有效 cookie → 200
  - `metrics`/`health` 仍公開 → 200

### Phase 3 — Session 綁 user + 資料隔離（核心）

- `session_metadata` 加 `user_id` migration + index。
- runtime `create/list/get` 加 `user_id`；端點層比對擁有權。
- `list_sessions` 只回自己的；存取他人 session/子資源/workspace → 404。
- **測試** `tests/test_session_isolation.py`：
  - userA 建 session → userB `GET /sessions` 看不到
  - userB 直接打 userA 的 `/sessions/{id}/messages` → 404
  - userB 打 userA 的 `/sessions/{id}/workspace/tree` → 404
  - legacy（user_id=NULL）session 不出現在任何人列表
  - 同一 user 跨登入 session 仍可見

### Phase 4 — 前端

- `auth` store、Login/Register 頁、router guard、`credentials: 'include'`、EventSource `withCredentials`、401 導向。
- **驗證**：`npm run build` 通過；手動走 註冊→登入→只見自己 session→登出 流程（可用 webapp-testing/Playwright 驗收）。

---

## 10. 風險與回滾

| 風險 | 緩解 |
|------|------|
| Phase 3 改動面廣（runtime 多方法 + 所有 session 端點），易漏過濾 | 測試先行；隔離測試覆蓋「越權回 404」；逐端點檢查 |
| EventSource 漏開 `withCredentials` → 串流靜默失敗 | §8.3 標記；前端冒煙測試三條串流 |
| `SESSION_SECRET` 未設 → 重啟後 cookie 全失效 | 設定文件 + 啟動檢查 |
| legacy session 變不可見造成「資料不見」誤會 | 文件說明；保留後端可見，必要時提供歸戶 script |

每個 phase 獨立 commit，出問題可單獨 revert；Phase 1–2 不動既有資料，Phase 3 只「新增欄位」不刪欄位，向下相容。

---

## 11. 對既有功能的影響

- 既有測試大量直接打 `/sessions`、`/chat`（未帶 cookie）→ Phase 2 後會變 401。**對策**：提供 pytest fixture（`authed_client`）幫測試自動註冊+登入帶 cookie；或讓既有 endpoint 測試改用該 fixture。這部分在 Phase 2 一併處理，避免打爛現有 CI。
