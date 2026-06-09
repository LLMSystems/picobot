# Configuration

picobot 的後端設定來自三處：環境變數（`.env`）、設定檔（JSON）、與啟動參數。

## 環境變數（`.env`）

放在專案根目錄：

```env
OPENAI_API_KEY=your_api_key_here
CORS_ALLOWED_ORIGINS=web_url_here
TAVILY_API_KEY=tvly-your_api_key_here

# 認證 / 權限
SESSION_SECRET=change-me-to-a-long-random-string   # 簽 cookie 用；未設會用臨時值，重啟即登出所有人
ADMIN_USERNAMES=alice,bob                           # 管理者帳號（逗號分隔，大小寫不敏感）
```

可選：

```env
OPENAI_BASE_URL=http://localhost:11434/v1
SESSION_COOKIE_SECURE=true       # 部署在 HTTPS 後設為 true
PICOBOT_EXEC_SANDBOX=0           # 關閉 exec 的 bubblewrap 沙箱（除錯用，預設啟用）
```

> 帳號由使用者自行在登入頁註冊（無公開 admin 後台）。要成為管理者，把帳號名加進 `ADMIN_USERNAMES` 後重啟後端。

## 設定檔

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

## 告警規則 `alerts.yaml`（可選）

在 repo root 放一份 `alerts.yaml` 就會啟用 Dashboard 的 Alerts 區塊。檔案不存在 server 一樣會啟動，只是不會有任何告警。schema 與設計細節見 [dashboard_metrics.md](../dashboard_metrics.md)。

```yaml
rules:
  - name: high_cpu_sustained
    display_name: CPU 持續過高
    description: CPU 持續高於 80%（超過 5 分鐘）
    severity: warning           # info | warning | critical
    metric_path: system.cpu_percent
    comparator: ">"
    threshold: 80
    for_seconds: 300
```

## 啟動後端

```bash
python3 fastapi_server.py --config example_config.json --host 0.0.0.0 --port 8000
```

常用參數：

- `--db-path sessions_async.db` — 明確指定 SQLite 檔案位置
- `--alerts-config /path/to/alerts.yaml` — 指定告警設定檔（預設 `./alerts.yaml`）

或用腳本：

```bash
sh start_fastapi_server.sh
# 對外服務：
HOST=0.0.0.0 PORT=8000 sh start_fastapi_server.sh
```

## SQLite 儲存內容

預設以 AioSQLite 儲存：

- users（帳號 + argon2 密碼雜湊）
- session message history（含 owner `user_id`）
- subagent runs / timeline events
- metrics snapshots（7 天）
- chat token usage events（7 天）
- alert events + silences（30 天）

## 以函式庫方式使用（純 Python）

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


if __name__ == "__main__":
    asyncio.run(main())
```
