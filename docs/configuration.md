# Configuration

picobot 的後端設定來自三處：環境變數（`.env`）、設定檔（JSON）、與啟動參數。

## System dependencies

核心後端（聊天、工具、workspace）只需要 Python 套件（`pip install -e .` 會一併裝好 `argon2-cffi`、`itsdangerous` 等）。但**網頁瀏覽**與 **exec 沙箱**需要額外的系統層套件：

| 用途 | 需要安裝 |
|------|----------|
| exec 檔案沙箱 | `bubblewrap`（未裝會自動 fallback 為直接執行） |
| 網頁瀏覽（agent-browser） | Node.js / npm、`npm i -g agent-browser`、`agent-browser install`（下載 headless Chrome） |
| Chrome 執行庫 | `libnspr4 libnss3 libatk-bridge2.0-0 libatk1.0-0 libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2 libpango-1.0-0 libcairo2 libatspi2.0-0 libgtk-3-0 ca-certificates` |
| 字型（截圖含中文/emoji） | `fontconfig fonts-noto-cjk fonts-noto-color-emoji fonts-dejavu-core fonts-liberation`，裝後跑 `fc-cache -fv` |
| 虛擬顯示（無頭環境） | `xvfb`，啟動 `Xvfb :99 -screen 0 1280x800x24 -nolisten tcp &` 並 `export DISPLAY=:99` |
| 版本控制（部分工具） | `git` |

> **最省事的方式**：在 Debian/Ubuntu 直接跑 [`start_fastapi_server.sh`](../start_fastapi_server.sh)（需要 `apt-get` / root），它會裝齊上面所有東西、起好 Xvfb，然後啟動後端。
>
> 若不需要瀏覽器功能，可略過 agent-browser / Chrome / Xvfb / 字型，只裝 `bubblewrap`（建議）即可。

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
