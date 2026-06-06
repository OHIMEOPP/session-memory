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
| `hooks/hooks.json` | `SessionStart` → 跑 `deploy_statusline.py`（自動部署 usage statusLine）；`SessionEnd` → 跑 `extract_session.py`（detached 背景，不卡退出）；`UserPromptSubmit` → 起綠色「作業中」桌寵；`Stop` → 同一隻翻成「處理完成」並關 |
| `scripts/session_mem_common.py` | 分艙 DB 路徑 + embedding 後端（store/query 共用）|
| `scripts/extract_session.py` | 萃取 worker：讀 transcript → `claude -p` 摘要 → embed 入庫 |
| `scripts/query_sessions.py` | 查詢：`"問題"` / `--list` / `--status` / `--min-score` / `-k`|
| `scripts/session_pet.py` | 右下角顏文字桌寵（cosmetic）。綠色寵=對話一回合「作業中→處理完成」（`UserPromptSubmit` 建 `.busy` + 起視窗，`Stop` 刪 `.busy` 令其翻完成；同一隻）；藍色寵=session 萃取中→完成（`LIFEWIKI_PET=0` 關）|
| `scripts/usage_statusline.ps1` | usage 狀態列**顯示邏輯**：常駐顯示 `/usage` 的 session(5h 滾動窗)+week(7d) 用量%（+ context 保底）。改樣式只改這支，`/plugin update` 即散布——見「usage statusLine」章節 |
| `scripts/sm-statusline-wrapper.ps1` | statusLine **橋接 wrapper 模板**：由 `deploy_statusline.py` 自動複製到 `~/.claude/scripts/`。動態定位 plugin cache 最高版、轉交 stdin（因 statusLine 不展開 `${CLAUDE_PLUGIN_ROOT}`、cache 路徑含版本號）|
| `scripts/deploy_statusline.py` | `SessionStart` hook：冪等部署 wrapper 到 user space + 首次補 `settings.json` 的 statusLine（已有則不動）。換機裝 plugin 即全自動 |
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

### 怎麼運作（換機全自動，免手動）

裝好 plugin 後，`SessionStart` hook（`deploy_statusline.py`）會自動：

1. 把 `scripts/sm-statusline-wrapper.ps1` **冪等複製**到 `~/.claude/scripts/`（隨 `/plugin update` 一起更新）
2. 若 `settings.json` 還沒有任何 `statusLine`，**自動補上**指向該 wrapper 那行（已有則完全不動，尊重你既有設定）

所以**換機只要裝 plugin**（`/plugin marketplace add` → `install` → `update`），重開一個新 session
就會生效——不用手動放 wrapper、也不用手動改 settings.json。

> statusLine 在 **session 啟動時載入一次**，所以 hook 這次寫的設定通常**下一個 session** 才看得到。

### 為什麼要這套機制（架構）

- Claude Code **不支援 plugin 在 manifest 註冊主 `statusLine`**（只開放 `agent` / `subagentStatusLine`），
  也**不會在 user settings 的 statusLine 指令裡展開 `${CLAUDE_PLUGIN_ROOT}`**，plugin cache 路徑又含版本號。
  → 故 wrapper 必須住固定的 user space 路徑，由 hook 部署；顯示邏輯則留在 plugin、隨版本走。
- `deploy_statusline.py` 改 settings.json 採**保守策略**：`utf-8-sig` 讀（容忍 BOM）、只在缺 `statusLine` 時加、
  保留其餘設定、atomic 寫回、失敗不擋 session 啟動。寫入的路徑用**正斜線**。

> ⚠ Windows 路徑**務必正斜線 `/`**：Claude Code 在 Windows 經 sh-like shell 執行 statusLine 指令，
> 反斜線 `\` 會被當 escape 吃掉 → 路徑壞 → command 靜默失敗（狀態列空白無報錯）。

### 手動接線（不想用自動、或想自訂時）

```json
"statusLine": {
  "type": "command",
  "command": "powershell -NoProfile -ExecutionPolicy Bypass -File C:/Users/User/.claude/scripts/sm-statusline-wrapper.ps1"
}
```

改顯示樣式（進度條格數、顏色、加 reset 倒數）只改 plugin 端 `scripts/usage_statusline.ps1` 並 `/plugin update`。

> macOS / Linux：目前自動部署與 wrapper 為 Windows PowerShell 版；需提供 `.sh` 版 wrapper +
> `usage_statusline.sh` 顯示邏輯，並在 `deploy_statusline.py` 依平台選對應檔。

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
