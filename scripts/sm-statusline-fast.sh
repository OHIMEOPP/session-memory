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
cache="$base/sm_statusline_cache.txt"
injson="$base/sm_statusline_last.json"
lock="$base/sm_statusline_refresh.lock"
wrapper="$base/sm-statusline-wrapper.ps1"

# 1) 存下 Claude Code 由 stdin 餵進來的 session JSON（給背景 refresher 用），瞬間完成
cat - > "$injson" 2>/dev/null

# 2) 立刻吐出目前快取 —— 這就是 render 路徑，純 cat、零 PowerShell
[ -f "$cache" ] && cat "$cache"

# 3) 背景非阻塞重算快取：8s stale-guard 鎖防 stampede / 防卡死；nohup+disown 撐過父進程結束
now=$(date +%s 2>/dev/null || echo 0)
lockts=$(stat -c %Y "$lock" 2>/dev/null || echo 0)
if [ ! -e "$lock" ] || [ $((now - lockts)) -ge 8 ]; then
  : > "$lock"
  nohup bash -c '
    out=$(powershell -NoProfile -ExecutionPolicy Bypass -File "'"$wrapper"'" < "'"$injson"'" 2>/dev/null)
    if [ -n "$out" ]; then printf "%s" "$out" > "'"$cache"'.tmp" && mv -f "'"$cache"'.tmp" "'"$cache"'"; fi
    rm -f "'"$lock"'"
  ' >/dev/null 2>&1 &
  disown 2>/dev/null
fi
exit 0
