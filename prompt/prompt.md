# AI 協作開發說明

**使用工具 : Claude Code**

## 人與 AI 的協作模式

本次前後端開發採用「人工主導、AI 協作」+ skill 的方式進行開發。由我負責定義前後端架構、實現要求，主要是根據 `./simplified_chatbot` 為核心開發前後端，我自己主要熟悉有經驗的前後端架構是 vue3 + fastapi，vue3 的好處是 Vue 3 + Vite 有提供模組化的開發體驗，而且原生 Fetch 與 Vue 內建狀態管理保持架構輕量，易維護與擴展。FastAPI 的話是因為異步、型別安全與自動 API 文件，所以以這個組合進行開發

再開發之前我自己準備兩個 skill，一個是 [shadcn-vue-tailwind-frontend](../prompt/skills/shadcn-vue-tailwind-frontend/SKILL.md)，主要是一份針對 Vue 3 + shadcn-vue + Tailwind CSS v4 技術棧的前端開發規範。另外一份是 [fastapi-job-api-backend](../prompt/skills/fastapi-job-api-backend/SKILL.md)，是 FastAPI 後端開發規範，定義如何建構接受請求

上面兩份 skill 都是根據我希望這個 web-agent 該怎麼開發設計的 

這樣的協作模式讓我可以保有對專案方向與品質的決策權，同時利用 AI 加快整理、撰寫與分析的速度

## 實際協作紀錄

本專案的協作過程可分為 Agent/前端/後端需求規格文檔撰寫、規格收斂、協作開發與測試四個階段，並分別反映在既有文件中。

### Agent
過往因有看過一些 Agent 框架，並自行整理其架構圖，可參考以下[連結](https://gitmind.com/app/docs/fudhcb6h)，因此直接參考其架構作為基礎進行開發，包含基本 Agent loop、tool calling、session、操作workspace、skill、目標是瀏覽器 Agent，因此需要異步、流式 event 支持、資料庫存取。　AI 主要協助一些 tool 撰寫、測試撰寫、供應商 provider 支持。還有 Agent 評估框架撰寫

### 後端
我的構想是，基本要支持流式、非流式後端支持，且因為是 Agent 因此每個新對話都需要有獨立的工作區可以操作，因此會以 session_id 創建獨立 workspace，需要的端口包含多 session 管理（建立、重新命名、刪除）、串流即時顯示 AI 回答、Workspace 管理 (列出 workspace 目錄內容、檔案)。AI 主要協助一些端口開發，例如資料庫增刪查改、根據[fastapi-job-api-backend](../prompt/skills/fastapi-job-api-backend/SKILL.md) fastapi 骨架開發、[後端開發文檔](../doc/frontend_api_reference.md) 撰寫

### 前端
基本需要開發的 : 多 session 管理、Markdown 完整渲染、工具呼叫視覺化、Workspace 面板（檔案樹 + 檔案預覽)、可拖拉調整寬度的三欄版面（sidebar、主聊天、workspace）。AI 主要協助前端基礎頁面開發，聊天紀錄sidebar、Workspace 面板、[前端設計文檔](../doc/frontend_interaction_spec.md) 撰寫、[前端開發文檔](../doc/frontend_vue_implementation.md) 撰寫、[前端補充開發文檔](../doc/frontend_features_supplement.md) 撰寫


## Prompt 紀錄

本節記錄各開發階段與 AI 協作時所使用的代表性 prompt，方便回顧當時的指令意圖與邊界設定。

### Agent

代表性 prompt 包含 : 

- 請幫我實作一個 read_file_tool 就好，不要另外做 write 或 list。這個工具只負責讀取文字檔，輸入需要有 path，這個 path 必須是相對於 session workspace 的相對路徑；另外可以支援選填的 encoding（預設 utf-8）和 max_chars（預設 20000，用來限制回傳長度）。路徑安全要做完整，包含先把路徑 resolve 後再檢查是否仍在 workspace 內，避免 ../ 穿越，也要避免透過符號連結跳出 workspace；如果 path 不存在、指向資料夾，或不是可正常解碼的文字檔，都請回傳清楚錯誤。請注意任何例外都不要直接拋到外層。然後需要trace file的狀態，避免時間差導致Agent 理解錯


- 請幫我實作 OpenAI-compatible provider，需支援 tool calling 與串流（stream=True）兩種模式，介面統一為 async def complete(messages, tools, stream)，然後 gpt5 跟 gpt4 系列有一個差別記得做出來，就是 gpt5 不支援 max_tokens，要傳 max_completion_tokens 且不需要傳 temperature



- 請參考 `simplified_chatbot/runtime/local_runtime.py` 幫我寫一個 eval runner 框架，不是單純單元測試，而是給 agent 一批真實任務、實際跑一次，收集輸出、事件、工具使用情況、workspace 結果，然後用rule base scoring，每一題至少要有 id(session_id)、category(tool、workspace)、prompt、expected_tools、expected_files、setup_files，然後Agent回答根據 expected_tools、expected_files計算準確度

### 後端

- /fastapi-job-api-backend，根據 [後端設計文檔](../doc/fastapi_chat_endpoints_design.md) 幫我建立 FastAPI 後端骨架，請分拆至獨立檔案，不要全塞在 main.py。


- 請幫我用 SQLite + aiosqlite 實作 session store，
支援 create、get、list、rename、delete session，
每個 session 紀錄 session_id、title、created_at、updated_at。


### 前端

- /skill shadcn-vue-tailwind-frontend，並根據[前端設計文檔](../doc/frontend_interaction_spec.md)、[前端開發文檔](../doc/frontend_vue_implementation.md)幫我用 Vue 3 + shadcn-vue + Tailwind CSS v4 
建立三欄版面：左側 session sidebar、中間聊天區、右側 workspace 面板。
三欄寬度皆可拖拉調整，最小 / 最大限制參考設計稿。



## AI 在本專案中的具體貢獻

AI 在本專案中的貢獻主要集中在以下幾個面向：

- 協助我整理Agent端、前後端開發文檔，包含Agent 功能實現、 api 端點開發協作與前端介面文檔開發
    - [後端設計文檔](../doc/fastapi_chat_endpoints_design.md)
    - [後端開發文檔](../doc/frontend_api_reference.md)
    - [前端設計文檔](../doc/frontend_interaction_spec.md)
    - [前端開發文檔](../doc/frontend_vue_implementation.md)
    - [前端補充開發文檔](../doc/frontend_features_supplement.md)

- 前端頁面基礎開發、後端骨架開發
- Agent 核心功能開發

## 我如何驗證 AI 產出&調整

為了避免直接採信 AI 產出的內容，我在本專案中採用了幾種驗證方式。

- 前端 : 確認畫面操作無誤、型別檢查、自行跑測試。
- 後端 : 初版開發完後確保型別定義正確，資料庫寫入正常、端口測試是否正常
- 對代碼進行人工複查與跑測試，特別是Agent流式輸出+tool調用的情況
- 針對 AI 產出的規範內容進行人工修訂，避免語意模糊、過度延伸或與實作脫節或是與我想法有出入，通常會充分與 AI 溝通。