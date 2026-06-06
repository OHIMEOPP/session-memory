---
description: 安裝 / 檢查 session 記憶系統的依賴與後端
---

協助使用者把 session 記憶系統的依賴裝好。依序做：

> ⚠ **Windows 多版本 Python 陷阱**：hook 與本 plugin 的指令一律用 **`py -3`** 跑
> （而非 `py 檔.py`）。原因：`py 檔.py` 會解析腳本 shebang `#!/usr/bin/env python3`，
> 去 PATH 搜 `python3`，常命中 **Microsoft Store 的 0-byte 假 stub**（exit 9009、零輸出，
> 看起來像沒裝套件其實根本沒跑）。`py -3` 直接鎖「已註冊的真 Python 3」，跳過 PATH 搜尋、
> 對假 stub 免疫。**檢查與安裝都鎖同一個直譯器**：檢查用 `py -3 檔.py`、安裝用 `py -3 -m pip`。

1. **測 chromadb 是否已裝**（鎖真 Python，確保是 hook 會用的那個）：
   ```
   py -3 "${CLAUDE_PLUGIN_ROOT}/scripts/query_sessions.py" --list
   ```
   - 印出「共 N 個 session」→ 已裝好，直接到第 3 步。
   - 印出「⚠ chromadb 未安裝 …」→ 進第 2 步。
   - （macOS / Linux 把 `py -3` 換成 `python3`。）

2. **沒裝就裝**（唯一硬依賴，預設後端零 ollama、零 API key）。
   裝進「檔案執行會用到的那個 Python」：
   ```
   py -3 -m pip install chromadb
   ```
   （macOS / Linux：`python3 -m pip install chromadb`。）
   裝完**重跑第 1 步驗證**——`py -3 -m pip` 與 `py -3 檔.py` 鎖的是同一個直譯器，
   正常不會錯位；若仍報未安裝，用 `py -0p` 確認 `py -3` 實際指到哪個 Python 再對應安裝。
   首次查詢會下載一個小的 MiniLM onnx embedding 模型（需一次性網路）；
   若報 onnxruntime 缺失，補 `py -3 -m pip install onnxruntime`。

3. **回報後端選項**給使用者（預設 `chroma` 即可開箱用）：
   - `chroma`（預設）— 內建 MiniLM，中文較弱但堪用，零外部依賴。
   - `ollama` — 中文最強（bge-m3）。需裝 [Ollama](https://ollama.com) + `ollama pull bge-m3`，
     並設環境變數 `LIFEWIKI_EMBED_BACKEND=ollama`（寫入端與查詢端都要看得到）。
   - `openai` — 設 `OPENAI_API_KEY` + `LIFEWIKI_EMBED_BACKEND=openai`。
   ⚠ 換後端 = 既有向量作廢，先刪該專案的庫資料夾再重建（不同 embedding 空間，Chroma 會擋混用）。

4. **驗證**：
   ```
   py -3 "${CLAUDE_PLUGIN_ROOT}/scripts/query_sessions.py" --status
   ```
   能正常印出（✅ 或 ⏳）就代表裝好了。

裝好後，之後每個專案 `/exit` 或 `/clear` 都會自動把該 session 萃取進「該專案的艙」，
用 `/session-recall <問題>` 檢索。萃取主力走 claude CLI（你跑 Claude Code 就有），不需額外設定。
