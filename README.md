# session-memory（Claude Code plugin）

每次 Claude Code session 結束（`/exit`、`/clear`）自動把對話**智慧萃取**成結構化
繁中摘要，存進本機向量庫；下個 session 可按需語意檢索過去脈絡。

**全域安裝、對所有專案的 `SessionEnd` 觸發，但每個專案各自一個向量庫互不汙染** —
專案身分取自 Claude Code 注入的 `CLAUDE_PROJECT_DIR`，slug 化後當分艙子資料夾。

```
~/.claude/session-memory/
├── C--Users-u-proj-a/      ← 專案 A 的 chroma 庫（summaries/ + .pending/ + extract.log）
└── C--Users-u-proj-b/      ← 專案 B，各自獨立累積
```

## 組成

| 檔案 | 角色 |
|------|------|
| `hooks/hooks.json` | `SessionEnd` → 跑 `extract_session.py`（detached 背景，不卡退出）；`UserPromptSubmit` → 起綠色「作業中」桌寵；`Stop` → 同一隻翻成「處理完成」並關 |
| `scripts/session_mem_common.py` | 分艙 DB 路徑 + embedding 後端（store/query 共用）|
| `scripts/extract_session.py` | 萃取 worker：讀 transcript → `claude -p` 摘要 → embed 入庫 |
| `scripts/query_sessions.py` | 查詢：`"問題"` / `--list` / `--status` / `--min-score` / `-k`|
| `scripts/session_pet.py` | 右下角顏文字桌寵（cosmetic）。綠色寵=對話一回合「作業中→處理完成」（`UserPromptSubmit` 建 `.busy` + 起視窗，`Stop` 刪 `.busy` 令其翻完成；同一隻）；藍色寵=session 萃取中→完成（`LIFEWIKI_PET=0` 關）|
| `scripts/usage_statusline.ps1` | usage 狀態列：常駐顯示 `/usage` 的 session(5h 滾動窗)+week(7d) 用量%（+ context 保底）。**不由 plugin manifest 註冊**（Claude Code 不支援 plugin 提供主 statusLine），須由 user space wrapper 接線——見「usage statusLine」章節 |
| `commands/session-recall.md` | `/session-recall <問題>` — 檢索當前專案的記憶 |
| `commands/session-memory-setup.md` | `/session-memory-setup` — 裝依賴 / 選後端 |

## 安裝

這是 Claude Code plugin，透過 marketplace 機制安裝。marketplace 名為
`memory-digest`（見 `.claude-plugin/marketplace.json`），其下含 `session-memory` 一個 plugin。

### A. 本機 / 開發安裝（marketplace 指向本機資料夾）

改源碼、自己開發時用這條（marketplace 是 directory 來源，讀本機那份）。
在任一 Claude Code session 內依序執行：

```
/plugin marketplace add <這個 repo 在你機器上的絕對路徑>
# 例如：/plugin marketplace add C:\Users\user\dev\session-memory
/plugin install session-memory@memory-digest
/session-memory-setup          ← 裝 chromadb；預設 chroma 後端零 ollama、零 API key
```

> `marketplace add` 指向**含 `.claude-plugin/marketplace.json` 的資料夾**（就是這個 repo 根）。
> 例：Windows `C:\path\to\session-memory`、macOS/Linux `~/path/to/session-memory`。

### B. 跨裝置安裝（從 GitHub）

```
/plugin marketplace add OHIMEOPP/session-memory
/plugin install session-memory@memory-digest
/session-memory-setup
```

> GitHub 來源的 marketplace 名一樣取自 `marketplace.json` 的 `name`，所以仍是 `memory-digest`。

### 生效（兩條路徑都需要）

安裝後會提示 `Run /reload-plugins to apply`——**當前 session 不會立即掛上 hook**：

1. `/reload-plugins`，或乾脆**關終端、開新 session**（較保險）。
2. 驗收：隨便聊 2~3 輪 → `/exit` → 等 10~60 秒，確認
   `~/.claude/session-memory/<該專案 slug>/` 下生出 `summaries/*.md`，
   且 `extract.log` 出現 `OK stored`。

> ⚠ plugin 實際執行的是 **cache 副本**
> （`~/.claude/plugins/cache/memory-digest/session-memory/<version>/`），不是這個源碼資料夾。
> 改了源碼要 `/plugin update` 才會同步到 cache。
> 另：`/hooks` 面板**不會**列出 plugin 掛的 hook（UI 限制），顯示 "No hooks configured"
> 不代表沒掛——以實際生出 `summaries/` 為準。

裝好後任何專案 `/exit` 、 `/clear` 就會自動萃取進該專案的艙，`/session-recall <問題>` 檢索。

## 更新（GitHub 有新版時）

marketplace 名是 `memory-digest`，更新分兩種來源：

### 從 GitHub 安裝者（B 路徑）

```
/plugin marketplace update memory-digest    ← 對 GitHub 來源做 git pull，抓最新 marketplace + plugin
/plugin update session-memory@memory-digest ← 把 cache 副本更新到最新版
/reload-plugins
```

> `marketplace update` 只刷新清單（含 git pull）；`plugin update` 才真的把跑的 **cache 副本**換新。兩步都要。

### 本機 directory 安裝者（A 路徑）

marketplace 指向本機資料夾，所以先把資料夾本身 `git pull`，再更新 plugin：

```
# 先在 repo 資料夾：git pull
/plugin update session-memory@memory-digest
/reload-plugins
```

> directory 來源讀的是本機那份檔案，`git pull` 後 `/plugin update` 就會把新內容同步進 cache。
> 若 `marketplace.json` 的 `version` 沒升，Claude Code 可能視為「已是最新」而不更新——
> 改源碼要散佈時記得把 `.claude-plugin/plugin.json` 與 `marketplace.json` 的 `version` 一起升號。

## usage statusLine（狀態列常駐顯示用量%）

在 Claude Code 底部狀態列常駐顯示 `/usage` 的兩個關鍵數字：
`session`（5 小時滾動窗用量%）與 `week`（7 天窗用量%），外加 context 窗用量保底。

> ⚠ 限制：`rate_limits` 那兩個百分比**只**出現在 statusLine 餵入的 stdin JSON，
> 且限 **Claude.ai Pro/Max、本 session 首次 API 回應之後**。剛開 session / 非 Pro·Max
> 時退回顯示 context 窗用量。**hook 完全拿不到這些數字**，所以做不進桌寵，只能走 statusLine。

### 為什麼要一個 user space wrapper

Claude Code **不支援 plugin 在 manifest 註冊主 `statusLine`**（只支援 `agent` /
`subagentStatusLine`），而且**不會在 user settings.json 的 statusLine 指令裡展開
`${CLAUDE_PLUGIN_ROOT}`**——plugin cache 路徑又含版本號，每次升版就變。

所以採混合：顯示邏輯（`scripts/usage_statusline.ps1`）住 plugin、隨 `/plugin update` 走；
user space 放一個一次性 thin wrapper，動態定位 plugin cache 最高版並轉交 stdin。

### 接線（一次性，Windows）

1. 放 wrapper `~/.claude/scripts/sm-statusline-wrapper.ps1`：

   ```powershell
   $ErrorActionPreference = 'SilentlyContinue'
   $raw = [Console]::In.ReadToEnd()
   $base = Join-Path $env:USERPROFILE '.claude\plugins\cache\memory-digest\session-memory'
   $target = $null
   if (Test-Path $base) {
       $dir = Get-ChildItem $base -Directory |
           Where-Object { $_.Name -match '^\d' } |
           Sort-Object { try { [version]($_.Name) } catch { [version]'0.0.0' } } -Descending |
           Select-Object -First 1
       if ($dir) {
           $cand = Join-Path $dir.FullName 'scripts\usage_statusline.ps1'
           if (Test-Path $cand) { $target = $cand }
       }
   }
   if ($target) { & $target -Raw $raw }
   else { try { $d = $raw | ConvertFrom-Json; [Console]::Out.Write($d.model.display_name) } catch { } }
   ```

2. `~/.claude/settings.json` 加：

   ```json
   "statusLine": {
     "type": "command",
     "command": "powershell -NoProfile -ExecutionPolicy Bypass -File C:/Users/User/.claude/scripts/sm-statusline-wrapper.ps1"
   }
   ```

   > ⚠ Windows 路徑**務必用正斜線 `/`**。Claude Code 在 Windows 經 sh-like shell 執行
   > statusLine 指令，反斜線 `\` 會被吃掉導致路徑壞掉、command 靜默失敗（狀態列空白）。
   > `powershell -File` 本身吃正斜線沒問題。（plugin 的 `hooks.json` 一直用正斜線就是這原因。）

3. 重啟 Claude Code session 生效。wrapper 寫一次就不用再碰；之後改顯示樣式只改 plugin 端
   `scripts/usage_statusline.ps1` 並 `/plugin update`。

> macOS / Linux：把 wrapper 改寫成 shell 版（`~/.claude/plugins/cache/memory-digest/session-memory/*/scripts/` 取最高版 → 跑對應腳本），並提供 `usage_statusline.sh` 版顯示邏輯。

## 後端 / 可調 env

| env | 預設 | 說明 |
|-----|------|------|
| `LIFEWIKI_EMBED_BACKEND` | `chroma` | `chroma` / `ollama`(bge-m3，中文最強) / `openai` |
| `LIFEWIKI_DB_ROOT` | `~/.claude/session-memory` | 庫根目錄 |
| `LIFEWIKI_EXTRACT_BACKEND` | `claude` | 萃取 LLM：`claude` CLI 主力，fallback `ollama` |
| `LIFEWIKI_OLLAMA_LLM` | `qwen3.5:9b` | fallback 萃取模型 |
| `LIFEWIKI_PET` | `1` | `0` 關桌寵 |

⚠ 換 embedding 後端 = 該專案既有向量作廢，先刪該艙資料夾再重建。

## 已知邊界

- `SessionEnd` 不保證 100% 觸發：正常 `/exit`、`/clear` 會；當機 / 強制 kill / 秒關機可能漏該次。
- 跨裝置不同步：各機各專案獨立庫。
- 平台：`hooks.json` 與 commands 預設用 Windows 的 `py -3`（鎖真 Python、繞過 shebang PATH 搜尋，避免命中 Microsoft Store 假 `python3` stub 而 exit 9009 靜默失敗）；macOS / Linux 需改 `python3`。
