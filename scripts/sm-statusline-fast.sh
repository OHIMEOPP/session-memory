#!/usr/bin/env bash
# 零延遲 statusLine —— render 路徑不碰 PowerShell。
#
# 為什麼要這支：Claude Code 對 statusLine 指令有逾時，而在 Windows 上 powershell.exe 每次
# 冷啟動本身就 ~0.7-1s，直接撞上/超過逾時 → Claude Code 丟棄結果 → 狀態列整條空白
# （症狀：設定與腳本都正確、手動跑也正常，但狀態列就是不顯示、重啟也沒用）。
# 解法：把「啟動 PowerShell」這件慢事移出 render 路徑。
#   - render 路徑（Claude Code 等待的那段）：只 cat 一個快取檔，毫秒級回傳、穩過逾時。
#   - 真正的渲染（usage_statusline.ps1，含 PowerShell）交給背景 daemon，把結果寫進快取。
#
# 0.8.5 起：背景渲染改成「每個 session 一個長駐 daemon」（sm-statusline-daemon.ps1），
# 本檔只負責在心跳過期時把它補起來。舊做法是每次刷新都 nohup 一個 bash + 一個 powershell，
# 在 Windows 上會**每輪配一個新 console** → 終端視窗瘋狂閃現，且卡住的行程會持續累積
# （實測開機數小時後 67 個 conhost / 57 個 bash / 12 個活超過一小時）。詳見 daemon 檔頭。
#
# __SCRIPTS_DIR__ 由 deploy_statusline.py 在部署時替換成 ~/.claude/scripts 的絕對路徑
# （Windows 磁碟代號 + 正斜線，bash 與 powershell -File 皆可吃）。
set +e
base="__SCRIPTS_DIR__"
daemon="$base/sm-statusline-daemon.ps1"

# 心跳過期多久就補一個 daemon。daemon 每 2s 一輪，抓 15s 給足容錯（單輪渲染偶爾較久）。
STALE=15

# 1) 先把 Claude Code 由 stdin 餵進來的 session JSON 整包收進變數（給背景 daemon 用）。
#    必須先收進來才能解析 session_id —— 快取要分艙到「每個 session 各一份」，
#    否則多專案/多 session 並跑時共用一個快取檔會互相覆蓋，狀態列閃成別的 session 的數字。
stdin=$(cat -)

# 2) 從 JSON 抽出 session_id 當快取 key（render 路徑只跑 grep/sed，微秒級、零 PowerShell）。
#    清成檔名安全字元；抽不到就退回 default（單艙，行為等同舊版）。
sid=$(printf '%s' "$stdin" | grep -oE '"session_id"[[:space:]]*:[[:space:]]*"[^"]+"' | head -1 \
      | sed -E 's/.*"session_id"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/' \
      | tr -d '\r\n' | tr -c 'A-Za-z0-9._-' '_')
[ -n "$sid" ] || sid="default"

cache="$base/sm_statusline_cache_${sid}.txt"
injson="$base/sm_statusline_last_${sid}.json"
beat="$base/sm_statusline_beat_${sid}.txt"
spawn="$base/sm_statusline_spawn_${sid}.txt"

# 原子寫入：先寫 .tmp 再 mv（rename 在同分割區是原子的）。daemon 會讀這個檔，
# 若這裡用 `> injson` 直寫會先 truncate 再填，剛好撞上 daemon 讀檔時就讀到半截/空 JSON
# → ConvertFrom-Json 失敗 → 該次刷新回空 → 快取不更新（顯示閃一拍舊值）。mv 讓讀端永遠看到完整檔。
#
# 這個檔同時也是 daemon 的「session 還活著嗎」判準：它的 mtime 久沒動 daemon 就自殺。
printf '%s' "$stdin" > "$injson.tmp" 2>/dev/null && mv -f "$injson.tmp" "$injson" 2>/dev/null

# 3) 立刻吐出本 session 自己的快取 —— 這就是 render 路徑，純 cat、零 PowerShell
[ -f "$cache" ] && cat "$cache"

# 4) 確保背景 daemon 活著。判準取「心跳」與「上次嘗試啟動」兩者較新的一個：
#    只看心跳的話，daemon 若根本起不來（檔案缺失、PowerShell 政策擋），心跳永遠不存在
#    → 每次 render 都重試 → 退化成舊版的 spawn 風暴。spawn 標記讓重試也維持 STALE 秒一次。
if [ -f "$daemon" ]; then
  now=$(date +%s 2>/dev/null || echo 0)
  beatts=$(stat -c %Y "$beat" 2>/dev/null || echo 0)
  tryts=$(stat -c %Y "$spawn" 2>/dev/null || echo 0)
  last=$beatts
  [ "$tryts" -gt "$last" ] && last=$tryts

  if [ $((now - last)) -ge "$STALE" ]; then
    : > "$spawn"
    # -WindowStyle Hidden：整個 session 只會走到這裡一次，但仍讓那一次不要閃出視窗。
    # daemon 自己有 singleton 鎖，就算這裡重複觸發也只會有一個活著。
    nohup powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden \
          -File "$daemon" -Base "$base" -Sid "$sid" >/dev/null 2>&1 &
    disown 2>/dev/null
  fi
fi
exit 0
