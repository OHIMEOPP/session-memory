---
description: 關鍵字檢索當前專案過去 session 的記憶（摘要由 SessionEnd 自動累積）
argument-hint: [要回想的問題]
---

使用者想從「當前專案」的過去 session 記憶裡找相關脈絡。

檢索走 **BM25 關鍵字比對**（jieba 斷詞），只比字面：查詢詞要跟摘要裡寫的字一樣才找得到。
所以執行前**先把使用者的問題擴充成關鍵字**，再丟進查詢：

- 中英都放：`微軟` → `微軟 Microsoft M365`、`桌寵` → `桌寵 live2d pet`
- 加近義詞：`信件` → `信件 信箱 郵件 mail`、`不見` → `不見 消失`
- 加專有名詞：車號、場站代碼、檔名、repo 名、指令名
- 拿掉太泛的詞：「問題」「修復」「session」這類幾乎每份摘要都有，加了只會干擾

執行以下指令查詢（按專案分艙，會自動鎖定當前專案的艙）：

```
py -3 "${CLAUDE_PLUGIN_ROOT}/scripts/query_sessions.py" "<擴充後的關鍵字>"
```

- Windows 若中文輸出報 `cp950` 錯，前面加 `PYTHONUTF8=1`。
- `py -3` 強制鎖真 Python，繞過 shebang 的 PATH 搜尋，避免命中 Microsoft Store 假 `python3` stub。
- macOS / Linux 把 `py -3` 換成 `python3`。
- 沒有 `$ARGUMENTS`（使用者只打 `/session-recall`）時，改跑 `--list` 列出本專案所有 session。

> **分數怎麼看**：BM25 分數沒有上限，不同查詢之間不能比，只能跟同一次查詢的第 1 名比。
> 預設 `--rel 0.5`：低於第 1 名一半的不顯示。第 1 名遠高於第 2 名＝結果很明確；
> 前幾名分數接近＝查詢太泛，換更具體的關鍵字再查一次。
> 空 session（只有 `/clear`、`/exit`）與同一 session 的舊版摘要會自動略過。

拿到輸出後：
- 把撈到的相關 session 摘要納入考量，針對使用者問題「$ARGUMENTS」綜合回答（附上是哪次 session）。
- 排名第一不代表相關：**先判斷內容是否真的切題**，不相關的就忽略。
- 沒撈到或撈錯：換一組關鍵字（換同義詞、補英文、補專有名詞）**再查一次**，兩次都沒有才回報沒有紀錄。
- 若顯示 ⏳，表示前一個 session 還在背景萃取，告知使用者稍候再查。
- 若提示 jieba / rank_bm25 未安裝，請使用者跑 `/session-memory-setup`。
