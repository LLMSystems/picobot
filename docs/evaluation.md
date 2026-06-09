# Evaluation

評測分成兩組資料集：

- core agent 題庫：[agent_core_21.jsonl](../eval/datasets/agent_core_21.jsonl)
- browser 題庫：[browser_core_4.jsonl](../eval/datasets/browser_core_4.jsonl)

執行：

```bash
python3 eval/scripts/run_eval.py example_config.json eval/datasets/agent_core_21.jsonl
python3 eval/scripts/run_eval.py example_config.json eval/datasets/browser_core_4.jsonl --enable-llm-judge --judge-model gpt-4.1-mini
```

## 結果（gpt-5-mini 本地一輪，共 25 題）

- 純 rule-based：24 / 25 通過（`pass_rate = 0.96`）
- final（browser 題改採 llm-judge）：25 / 25 通過（`pass_rate = 1.0`）
- 細項：`tool_calling` 8/8、`workspace` 13/13、`browser` 4/4

涵蓋能力：多輪 agent loop 與工具調用、workspace 讀寫/搜尋/整理/產物生成、網站瀏覽/點擊/截圖驗證。

## 為什麼 browser 題用 LLM judge

browser 題操作流程高度開放，同一任務可能有不同但合理的 CLI 序列，因此不只看固定字串規則，而是同時參考：題目本身、agent 最終回答、workspace 文字 artifact、最終 screenshot、`agent-browser` skill 規則。

每題產生三種結果：

- `rule_pass`：只看檔案存在、文字命中、圖片大小等規則
- `llm_judge_pass`：由支援圖片輸入的 judge model 綜合判斷
- `final_pass`：browser 題以 `llm_judge_pass` 為最終結果，其他題型沿用 rule-based

## 隔離

eval runner 為每題建立獨立 `session_id` 與專屬 workspace，避免前一題的檔案或上下文污染後一題，更接近實際部署情境。

## Run 產物結構

每次執行在 [eval/runs](../eval/runs) 下產生一個新目錄（例 `2026-05-17_232301/`）：

```text
eval/runs/<run_id>/
  config_snapshot.json     # 設定快照，便於重現
  dataset_snapshot.jsonl   # 題庫快照，避免後續變更不可追溯
  run.json                 # 整體 summary：完成數、通過率、分類統計、每題摘要
  cases/<case_id>.json     # 單題完整結果：回答、工具使用、events、outputs、score、llm_judge/final_pass
  sessions/<session_id>.jsonl   # 該題對話歷史
  workspaces/<session_id>/      # 該題執行後的 workspace
```
