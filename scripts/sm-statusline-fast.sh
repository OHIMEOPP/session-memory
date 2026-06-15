#!/usr/bin/env bash
# 零延遲 statusLine —— render 路徑不碰 PowerShell。
#
# 為什麼要這支：Claude Code 對 statusLine 指令有逾時，而在 Windows 上 powershell.exe 每次
# 冷啟動本身就 ~0.7-1s，直接撞上/超過逾時 → Claude Code 丟棄結果 → 狀態列整條空白
# （症狀：設定與腳本都正確、手動跑也正常，但狀態列就是不顯示、重啟也沒用）。
# 解法：把「啟動 PowerShell」這件慢事移出 render 路徑。
#   - render 路徑（Claude Code 等待的那段）：只 cat 一個快取檔，毫秒級回傳、穩過逾時。
#   - 真正的渲染（usage_statusline.ps1，含 PowerShell）丟到背景非阻塞跑，把結果寫進快取，
#     供下一次 render 讀取。
# 代價：顯示內容約落後 1 個刷新（~1s）—— model/git/用量/花費/匯率/碎念無感，倒數秒數慢 1 拍。
#
# __SCRIPTS_DIR__ 由 deploy_statusline.py 在部署時替換成 ~/.claude/scripts 的絕對路徑
# （Windows 磁碟代號 + 正斜線，bash 與 powershell -File 皆可吃）。
set +e
base="__SCRIPTS_DIR__"
wrapper="$base/sm-statusline-wrapper.ps1"

# 1) 先把 Claude Code 由 stdin 餵進來的 session JSON 整包收進變數（給背景 refresher 用）。
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
lock="$base/sm_statusline_refresh_${sid}.lock"

printf '%s' "$stdin" > "$injson" 2>/dev/null

# 3) 立刻吐出本 session 自己的快取 —— 這就是 render 路徑，純 cat、零 PowerShell
[ -f "$cache" ] && cat "$cache"

# 4) 背景非阻塞重算快取：8s stale-guard 鎖防 stampede / 防卡死；nohup+disown 撐過父進程結束
now=$(date +%s 2>/dev/null || echo 0)
lockts=$(stat -c %Y "$lock" 2>/dev/null || echo 0)
if [ ! -e "$lock" ] || [ $((now - lockts)) -ge 8 ]; then
  : > "$lock"
  nohup bash -c '
    out=$(powershell -NoProfile -ExecutionPolicy Bypass -File "'"$wrapper"'" < "'"$injson"'" 2>/dev/null)
    if [ -n "$out" ]; then printf "%s" "$out" > "'"$cache"'.tmp" && mv -f "'"$cache"'.tmp" "'"$cache"'"; fi
    rm -f "'"$lock"'"
    # 順手清掉 1 天前的分艙殘檔（session 結束後不會再被讀，避免無限累積）
    find "'"$base"'" -maxdepth 1 -name "sm_statusline_*_*" -type f -mtime +1 -delete 2>/dev/null
  ' >/dev/null 2>&1 &
  disown 2>/dev/null
fi
exit 0
