---
description: 語意檢索當前專案過去 session 的記憶（向量庫由 SessionEnd 自動累積）
argument-hint: [要回想的問題]
---

使用者想從「當前專案」的過去 session 記憶裡找相關脈絡。

執行以下指令查詢（向量庫按專案分艙，會自動鎖定當前專案的艙）：

```
py "${CLAUDE_PLUGIN_ROOT}/scripts/query_sessions.py" "$ARGUMENTS" --min-score 0.5
```

- Windows 若中文輸出報 `cp950` 錯，前面加 `PYTHONUTF8=1`。
- macOS / Linux 把 `py` 換成 `python3`。
- 沒有 `$ARGUMENTS`（使用者只打 `/session-recall`）時，改跑 `--list` 列出本專案所有 session。

拿到輸出後：
- 把撈到的相關 session 摘要納入考量，針對使用者問題「$ARGUMENTS」綜合回答（附上是哪次 session）。
- 若顯示 ⏳，表示前一個 session 還在背景萃取，告知使用者稍候再查。
- 若空庫或無命中（低於門檻），如實說明沒有相關的過去紀錄，照常進行，別硬塞不相關舊事。
- 若提示 chromadb 未安裝，請使用者跑 `/session-memory-setup`。
