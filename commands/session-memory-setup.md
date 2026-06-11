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

---

## 5. Live2D 立繪桌寵（預設啟用 Wanko 狗狗）

**這是標準 setup 步驟，預設就把會動的 Live2D 立繪寵（Wanko 狗狗）裝好並啟用**——
使用者不用另外開口、不用換電腦再手動叫人裝。失敗（缺網／裝不動／離線）會**自動退回
顏文字寵**，永不影響記憶萃取功能，所以 setup 一律放心執行這步。

a. **裝 PySide6**（含 QtWebEngine；約 200MB，鎖 `py -3` 同一直譯器）：
   ```
   py -3 -m pip install PySide6
   ```
   裝完**務必用同一個 `py -3` 驗證**（機器常有多個 Python 3.x，裝錯邊 hook 會找不到）：
   ```
   py -3 -c "import PySide6; from PySide6.QtWebEngineWidgets import QWebEngineView; print('PySide6 OK')"
   ```
   印不出 OK＝裝到別的直譯器了（用 `py -0p` 看 `py -3` 指向誰）。hook 與桌寵 daemon 都鎖
   `py -3` / `sys.executable`，**務必確保 PySide6 在 `py -3` 這個直譯器底下**。
   - Windows 另需 **WebView2 / Edge runtime**（Win11、有裝 Edge 即內建，通常免裝）。
   - 角色模型與 pixi/cubism 引擎**首次執行從 CDN 載入**（需一次性網路；之後 Chromium 會快取）。

b. **啟用立繪模式**——把環境變數寫進 `~/.claude/settings.json` 的 `env`（hook 進程才看得到；
   沒有 `env` 區塊就建一個）。setup 直接幫使用者寫好，不用他自己編輯：
   ```json
   "env": {
     "SM_PET_STYLE": "live2d",
     "SM_PET_PERSIST": "1"
   }
   ```
   `SM_PET_STYLE=live2d` 啟用立繪（不設或設別的值＝維持顏文字寵）；`SM_PET_PERSIST=1`＝桌寵
   一直待在桌面（想要閒置 5 分自動「回家」就拿掉這行）。**env 改動下個 session 才生效。**
   想當場先看效果不必等：`py -3 "${CLAUDE_PLUGIN_ROOT}/scripts/live2d_pet.py" --demo`。

c. **其他可調環境變數**（皆選填）：
   | 變數 | 預設 | 說明 |
   |------|------|------|
   | `SM_PET_FRAME` | `half` | 取景：`half` 半身特寫 / `full` 全身 / `head` 大頭貼 |
   | `SM_PET_MODEL` | Wanko 狗狗 | 換模型：指向任一 Cubism 4 `*.model3.json` 的 URL（官方範例另有 Haru / Hiyori / Mao / Rice 等）|
   | `SM_PET_SCALE` | （自動） | 給了就用固定縮放，覆蓋 `SM_PET_FRAME` 自動取景 |
   | `SM_PET_CAPTION` | `1` | 設 `0` 關閉底部狀態字幕 |
   | `SM_PET_PERSIST` | `0` | 預設閒置滿 `SM_PET_IDLE_EXIT` 分鐘自動「回家」（視窗消失、有事再自動回來）；`1`＝永遠待在桌面 |
   | `SM_PET_IDLE_EXIT` | `5` | 閒置幾分鐘回家（關 daemon 釋放記憶體）；`0`＝永不 |

   立繪寵是**一隻常駐窗**（單例，每專案一隻），可拖曳移動、**雙擊關閉**。
   想先看效果不必開 hook：`py -3 "${CLAUDE_PLUGIN_ROOT}/scripts/live2d_pet.py" --demo`
   （每 3 秒輪播待機→作業中→等你回應→萃取中→完成五種狀態）。

> 預設模型是 Live2D 官方免費素材 **Wanko（狗狗）**（Free Material License，CubismWebSamples）；
> plugin 不內含模型檔，執行時才從 CDN 取，repo 保持乾淨、避免再散布授權問題。
> 無表情的模型（Wanko/Hiyori/Rice…）狀態切換靠動作+字幕區分；要臉部表情變化可換 Haru/Mao
> （8 表情）或 Natori（具名表情最多）。
