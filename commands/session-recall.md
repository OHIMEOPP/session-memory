---
description: 語意檢索當前專案過去 session 的記憶（向量庫由 SessionEnd 自動累積）
argument-hint: [要回想的問題]
---

使用者想從「當前專案」的過去 session 記憶裡找相關脈絡。

執行以下指令查詢（向量庫按專案分艙，會自動鎖定當前專案的艙）：

```
py -3 "${CLAUDE_PLUGIN_ROOT}/scripts/query_sessions.py" "$ARGUMENTS" --min-score 0.4
```

- Windows 若中文輸出報 `cp950` 錯，前面加 `PYTHONUTF8=1`。
- `py -3` 強制鎖真 Python，繞過 shebang 的 PATH 搜尋，避免命中 Microsoft Store 假 `python3` stub。
- macOS / Linux 把 `py -3` 換成 `python3`。
- 沒有 `$ARGUMENTS`（使用者只打 `/session-recall`）時，改跑 `--list` 列出本專案所有 session。

> **門檻為何是 0.4（偏低）**：預設 embedding 後端是 Chroma 內建 MiniLM，對**中文**語意
> 表達偏弱——連「query 與摘要主題完全相同」的命中，cosine 都只落在 ~0.44–0.50，整體分數被
> 壓在 0.4–0.5 這一帶。門檻設 0.5 會把真命中也切成假陰性，故降到 0.4 換回召回率。
> 代價：偶爾混進弱相關（甚至空的 `/exit` session，約 0.43）——**綜合回答時自行略過明顯不相關
> 或無內容的那筆**，別硬塞。想要中文召回更準可改用 ollama bge-m3 後端（見 `/session-memory-setup`）。

拿到輸出後：
- 把撈到的相關 session 摘要納入考量，針對使用者問題「$ARGUMENTS」綜合回答（附上是哪次 session）。
- 排名第一不代表相關：**先判斷內容是否真的切題，明顯不相關或空白的就忽略**，別因為它過了 0.4 就硬用。
- 若顯示 ⏳，表示前一個 session 還在背景萃取，告知使用者稍候再查。
- 若空庫或無命中（低於門檻），如實說明沒有相關的過去紀錄，照常進行，別硬塞不相關舊事。
- 若提示 chromadb 未安裝，請使用者跑 `/session-memory-setup`。
