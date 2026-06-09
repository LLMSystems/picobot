# exec 沙箱化 / 隔離設計評估（第 2 項）

> 狀態：**2a + 2b 已實作**（commit 見 git log；[shell.py](simplified_chatbot/tools/shell.py)）。2c（網路鎖定）未做。
>
> 實作摘要：
> - **2a**：spawn 加 `start_new_session=True`，timeout 改 `killpg`（不留孤兒）；shell 內 `ulimit -S -f`(4 GiB 單檔) + 一次性 exec 的 `ulimit -S -t`(CPU backstop)。
> - **2b**：bwrap 包裝 —— `--ro-bind /usr` + `/bin,/lib,/lib64,/sbin` symlink、`--ro-bind /etc`、`--tmpfs /tmp`、`--proc`/`--dev`、**只 `--bind` 該 session workspace（rw）**、`--unshare-{user,pid,ipc,uts}`、`--share-net`（保 CDP loopback）、`--die-with-parent`、`--new-session`；PATH/HOME 重設為系統 layout。
> - bwrap 不存在或工具非 workspace-restricted → fallback 直跑（仍有 2a）。可用 `PICOBOT_EXEC_SANDBOX=0` 關閉。
> - 測試預設關沙箱（測試用 venv 絕對路徑 python，不在沙箱內）；另有 skip-if-no-bwrap 的隔離測試驗證「看不到 workspace 外的檔案」。
> 前置：secret 已從 exec 環境剔除（commit `5ad55d7`，[shell.py](simplified_chatbot/tools/shell.py) `build_subprocess_env`）
> 目標讀者：picobot 維護者

---

## 1. 現況與威脅

`exec` 目前以**伺服器同一個 OS 使用者**在主機上直接跑：

- spawn：`bash -l -c <cmd>`，`cwd=<session workspace>`，env 已 scrub（[shell.py:_spawn](simplified_chatbot/tools/shell.py)）。
- 邊界：regex/deny-list（`../`、workspace 外絕對路徑、少數危險指令）—— **軟性、可繞過**（執行期解析的相對路徑、glob、語言內 API、`cd /` 後相對路徑…）。
- 沒有 OS 層隔離：共用檔案系統與身分、無 rlimit、網路不限。

**剩餘威脅（env scrub 之後）**：

| 威脅 | 現況是否擋得住 |
|------|----------------|
| 讀其他 user 的 workspace / 主機檔案（`/etc`、其他人 `.skills`、DB 檔） | ❌ regex 可繞過 |
| 寫壞主機 / 其他 workspace | ❌ |
| Fork bomb / 吃光記憶體 / CPU / 塞爆磁碟 | ⚠️ 只有經典 fork bomb 被 deny pattern 擋；其餘可 |
| 網路外連 exfiltrate / SSRF 打內網 | ❌ 無限制 |
| 讀 secret（環境變數） | ✅ 已 scrub |

**關鍵相容性限制（任何方案都要顧）**：

1. **agent-browser ↔ 共用 Chrome（CDP）**：exec 會跑 `agent-browser --cdp <port> ...`（[shell.py:_maybe_inject_cdp_port](simplified_chatbot/tools/shell.py)），連到 `ChromeProcess` 在 localhost 開的 CDP port。**沙箱若切斷 loopback，瀏覽器功能直接壞掉。**
2. **長生命週期 exec session**（`yield_time_ms` / `write_stdin`，[exec_session.py](simplified_chatbot/tools/exec_session.py)）：沙箱必須**撐過整個 session 生命週期**並能餵 stdin，不能只包單發指令。
3. **per-session workspace**：理想上沙箱只掛載「該 session 的 workspace」→ 用 OS 層補上目前 regex 缺口（跨 user 檔案隔離）。

---

## 2. 方案比較

| 方案 | 隔離強度 | 啟動成本 | 工程量 | 相依/環境需求 | agent-browser 相容 |
|------|----------|----------|--------|----------------|---------------------|
| **A. rlimit + setsid（不含沙箱）** | 低（只防資源濫用） | ~0 | 小 | 純 Python `resource`（POSIX） | ✅ 不影響 |
| **B. bubblewrap (bwrap)** | 中高（FS namespace、可選 net） | 很低（無 daemon、ms 級） | 中 | `bwrap` 套件 + unprivileged userns | ✅（`--share-net` 保留 loopback） |
| **C. nsjail** | 高（+ seccomp） | 低 | 中高（設定較繁） | `nsjail` 編譯/安裝 | ✅（需設定保留 net） |
| **D. Docker per-session 容器** | 最高（FS/net/pid/cgroup） | 高（容器生命週期、image） | 大 | Docker daemon（WSL2 用 Docker Desktop） | ⚠️ 需 host.docker.internal 或容器內 Chrome |
| **E. firejail** | 中（SUID profile） | 低 | 中 | `firejail`（SUID 疑慮） | ✅ |
| gVisor / Kata / microVM | 極高 | 高 | 很大 | 特殊 runtime | 視設定 |

### 重點解讀
- **A** 純資源限制，**不**隔離檔案/網路 —— 但零相依、純 Python，可**馬上做**且與其他方案疊加。
- **B bubblewrap** 是 Linux 上「per-command 檔案隔離」CP 值最高的：unprivileged user namespace、bind-mount **只掛該 session workspace（rw）+ 唯讀最小 rootfs（/usr,/bin,/lib）+ tmpfs /tmp**、`--die-with-parent`、可 drop caps。要瀏覽器就 `--share-net`（保留 loopback 到 CDP），要更嚴可只放 loopback。**真正把目前 regex 缺口補成 OS 邊界。**
- **D Docker** 隔離最強（含網路 namespace），但要管容器生命週期（綁 session）、掛 workspace volume、`exec` 進容器；長 session 要保持容器存活；瀏覽器要嘛容器內自帶 Chrome、要嘛走 `host.docker.internal` 到主機 CDP。**ops 與啟動成本最高。**

### 本機（這台 WSL2）實測結論
- **user namespace 可用**：`unshare -Ur` 成功、`max_user_namespaces=63413` → **bwrap 裝了就能用**。
- **bwrap 尚未安裝**：需 `sudo apt install bubblewrap`（Phase 2b 的唯一前置）。
- **Docker 不可用**：未啟動/未安裝 → 方案 D 在此環境直接出局。
- **Python `resource` 可用**：Phase 2a（rlimit）**現在就能做**，零相依。
- 目前 `_spawn` / `_spawn_session` **沒有** `start_new_session` 或 `preexec_fn` → 2a 的 setsid + rlimit 是實打實的缺口。

---

## 3. 建議：分階段

### Phase 2a — 資源限額（先做，便宜、無相依）
在 `_spawn` / `_spawn_session` 加 `preexec_fn`（POSIX）設 `resource.setrlimit`：
- `RLIMIT_CPU`（對齊 timeout）、`RLIMIT_AS`（記憶體上限）、`RLIMIT_NPROC`（防 fork bomb）、`RLIMIT_FSIZE`（單檔大小）、`RLIMIT_NOFILE`。
- `start_new_session=True`（setsid）→ timeout kill 時可整組 process group 收掉（目前只 kill 主行程，子孫可能殘留）。
- 風險低、不動架構、與 B/D 疊加。**擋掉資源濫用，但不隔離 FS/網路。**

### Phase 2b — bubblewrap 包裝（真正的隔離邊界）
把 spawn 改成 `bwrap [args] -- bash -lc <cmd>`：
- bind：`--ro-bind /usr /usr`、`/bin`、`/lib*`、`--bind <session_ws> <session_ws>`、`--tmpfs /tmp`、`--proc /proc`、`--dev /dev`。
- `--unshare-user --unshare-pid --unshare-ipc --unshare-uts`，網路 `--share-net`（保留 CDP；如要鎖網改用 slirp/loopback-only 方案）。
- `--die-with-parent`、`--new-session`、`--chdir <session_ws>`。
- **效果**：指令只看得到自己的 workspace + 唯讀系統，看不到別人 workspace / 主機檔 / DB；regex guard 變成「防呆」而非唯一防線。
- 與 2a 的 rlimit 疊加。需偵測 `bwrap` 是否存在 → 沒有則 fallback 到目前行為（並記 log/警告），避免在沒裝的環境壞掉。

### Phase 2c（可選）— 網路政策
若要防 exfiltrate/SSRF：用 bwrap 網路 namespace + 只放行 loopback（保 CDP），或加 egress allowlist。代價是很多「上網查資料/抓檔」類任務會受限 → 需與產品取捨，建議做成設定開關。

### 不建議現在做
Docker per-session（D）：除非你需要**網路 namespace 級**隔離或多租戶硬性保證，否則 ops/啟動成本不划算，且和「共用 Chrome」相容性要額外處理。

---

## 4. 對既有功能的風險

| 風險 | 緩解 |
|------|------|
| bwrap 未安裝 / WSL userns 關閉 → exec 全壞 | 啟動偵測，缺則 fallback 現行行為 + 警告；設定可強制要求 |
| agent-browser 連不到 CDP | `--share-net` 保留 loopback；加一個 browser 題的冒煙測試 |
| 長 session（write_stdin）在沙箱內存活/收訊 | 包裝長行程本身；`--die-with-parent` 確保 server 收掉時一起收 |
| rlimit 太嚴誤殺正常 build/test | 限額做成設定（預設寬鬆），可調 |
| eval / 測試環境沒有 bwrap | 測試走 fallback 路徑；另加「有 bwrap 時」的隔離測試（skip if 不存在） |

---

## 5. 定案（威脅模型：半信任 + 主要防檔案/資源）

選定 **2a（rlimit + setsid）→ 2b（bubblewrap）**，**不採 Docker**。

理由：在「半信任使用者、主要目標是彼此不能讀對方檔案/主機 secret、別把機器搞爆」的模型下，Docker 的額外價值（網路 namespace 隔離、硬性 cgroup）正好非必要，而其成本（per-session 容器生命週期、image 維護、啟動延遲）都得承擔。bwrap 正中需求：

- 啟動 ms 級、無 daemon、無生命週期管理；
- 沿用主機 toolchain（bind `/usr`），**零 image 維護**；
- `--share-net` 保留 loopback → agent-browser 連共用 Chrome CDP **零額外設定**；
- bind-mount 只掛該 session workspace → 跨 user 讀檔從 regex 軟防線升級成 **OS 真邊界**。
- 搭配 2a 的 rlimit 補資源限額（bwrap 本身不做 cgroup）。

> Docker 雖已可用且隔離最強，保留為未來「不可信/多租戶 + 需網路隔離」時再升級的選項（§2 方案 D）。

**落地順序**：
1. **2a 先上**（純 Python `resource`，零相依，本機已驗證可用）。
2. **2b**：需 `sudo apt install bubblewrap`（userns 本機已驗證可用）；bwrap 不存在時 fallback 現行行為 + 警告，避免弄壞沒裝的環境。
