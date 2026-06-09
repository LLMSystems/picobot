# Architecture

```text
picobot/
  simplified_chatbot/
    agent/          # agent loop, message flow, run result
    auth/           # users store + argon2 password hashing
    config/         # config schema / loader / env handling
    metrics/        # metrics service / snapshot / chat-usage stores
    alerts/         # alert rules engine + events store
    prompts/        # system prompt 與 prompt 組裝
    providers/      # OpenAI-compatible provider
    runtime/        # session runtime, SQLite store, subagent/event persistence
    server/         # FastAPI endpoints、schemas、auth deps (require_user/admin)
    skills/         # builtin / shared / per-user skills loader
    tools/          # file, patch, search, shell(sandboxed), subagent tools
  frontend/
    src/
      components/   # chat、layout、workspace、common UI 元件
      composables/  # useAutoScroll、useHorizontalResize、useVerticalSplit 等
      lib/          # api、sse、markdown、types
      stores/       # Pinia stores（auth、capabilities、sessions、chat、workspace、skills、mcp）
      views/        # ChatView、EmptyView、LoginView、RegisterView
  eval/             # eval datasets, runs, scripts
  tests/            # pytest 測試
```

## 設計文件

- [auth_design.md](../auth_design.md) — 認證與多使用者隔離
- [exec_sandbox_design.md](../exec_sandbox_design.md) — exec 沙箱化
- [dashboard_metrics.md](../dashboard_metrics.md) — 指標 / 告警
- [multi_agent_design.md](../multi_agent_design.md) — 多型別 agent

## 前端技術棧

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
