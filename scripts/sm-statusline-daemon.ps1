#!/usr/bin/env pwsh
# statusLine 背景 refresher —— 每個 session 一個長駐行程。
#
# 為什麼要這支（取代 0.8.4 之前「每次刷新 nohup 一個 bash + 一個 powershell」的做法）：
# 舊做法在 Windows 上每刷新一輪就新建行程，而從 detach 掉、沒有 console 的父行程啟動
# 主控台程式時，系統會**配一個新的 console 給它** → 使用者看到終端視窗瘋狂閃現。
# 加上 powershell 偶爾卡住不退（git/網路呼叫），孤兒行程會持續累積
# （實測：開機數小時後 67 個 conhost、57 個 bash、12 個活超過一小時）。
#
# 本檔的做法：整個 session 只起 **一個** powershell，內部迴圈重算快取。
#   - 每輪刷新是「同一個行程內的函式呼叫」，不再 spawn 任何子行程 → 零新視窗、零累積。
#   - 因為沒有行程建立成本，刷新間隔可以縮到 2s（舊做法受 8s 防重入鎖限制，反而更慢）。
#
# 生命週期由 heartbeat 檔控制，render 路徑（sm-statusline-fast.sh）只看心跳決定要不要補起一個：
#   - 每輪 touch 一次 heartbeat
#   - injson 超過 $IdleExitSec 沒被更新 ＝ 該 session 已結束 → 自殺
#   - 硬上限 $MaxHours 小時 → 自殺（防任何想不到的卡死狀態長生不老）
param(
    [Parameter(Mandatory = $true)][string]$Base,   # ~/.claude/scripts 絕對路徑
    [Parameter(Mandatory = $true)][string]$Sid,    # session_id（已由呼叫端清成檔名安全字元）
    # 每輪間隔。設 1 是為了讓 reset 倒數（顯示到秒）真的每秒跳——舊的 per-refresh spawn 架構
    # 每輪成本 300ms 起跳（powershell 冷啟 + git），跑不動每秒；改 daemon + git 分支快取後
    # 每輪只剩 6-21ms（同行程內函式呼叫、零子行程），1s 綽綽有餘。
    [int]$IntervalSec = 1,
    [int]$IdleExitSec = 120,                        # injson 多久沒更新就判定 session 已死
    [int]$MaxHours    = 12                          # 硬性壽命上限
)

$ErrorActionPreference = 'SilentlyContinue'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

$injson  = Join-Path $Base "sm_statusline_last_$Sid.json"
$cache   = Join-Path $Base "sm_statusline_cache_$Sid.txt"
$beat    = Join-Path $Base "sm_statusline_beat_$Sid.txt"
$lockDir = Join-Path $Base "sm_statusline_daemon_$Sid.lock"
$dbgFlag = Join-Path $Base 'sm_statusline_debug'
$dbgLog  = Join-Path $Base 'sm_statusline_debug.log'

# ── singleton ────────────────────────────────────────────────────────────────
# 用「建目錄」搶鎖：New-Item -ItemType Directory 在已存在時必失敗，是原子操作。
# 搶不到就看心跳——心跳夠新代表真有另一個活著的 daemon，本行程立刻退場；
# 心跳過期代表上一個 daemon 死了沒清乾淨，強制接管。
function Get-BeatAgeSec {
    if (-not (Test-Path $lockDir)) { return [int]::MaxValue }
    if (-not (Test-Path $beat))    { return [int]::MaxValue }
    try { return ((Get-Date) - (Get-Item $beat).LastWriteTime).TotalSeconds } catch { return [int]::MaxValue }
}

$got = $null -ne (New-Item -ItemType Directory -Path $lockDir -ErrorAction SilentlyContinue)
if (-not $got) {
    if ((Get-BeatAgeSec) -lt ($IntervalSec * 5)) { return }   # 有活著的同伴 → 讓位
    Remove-Item $lockDir -Recurse -Force -ErrorAction SilentlyContinue
    $got = $null -ne (New-Item -ItemType Directory -Path $lockDir -ErrorAction SilentlyContinue)
    if (-not $got) { return }                                  # 還是搶不到就放棄，下一輪 render 會再試
}

# ── 定位真正的渲染腳本（同 sm-statusline-wrapper.ps1 的邏輯：取 cache 內最高版本）──
# 只在啟動時解析一次；plugin 升版後 deploy_statusline.py 會換掉 heartbeat/lock 所在的腳本，
# 舊 daemon 自然會因為 session 結束而退場，不需要熱重載。
function Resolve-Renderer {
    $root = Join-Path $env:USERPROFILE '.claude\plugins\cache\memory-digest\session-memory'
    if (-not (Test-Path $root)) { return $null }
    $dir = Get-ChildItem $root -Directory |
        Where-Object { $_.Name -match '^\d' } |
        Sort-Object { try { [version]($_.Name) } catch { [version]'0.0.0' } } -Descending |
        Select-Object -First 1
    if (-not $dir) { return $null }
    $cand = Join-Path $dir.FullName 'scripts\usage_statusline.ps1'
    if (Test-Path $cand) { return $cand }
    return $null
}

# ── 在本行程內渲染一次 ───────────────────────────────────────────────────────
# usage_statusline.ps1 是用 [Console]::Out.Write 輸出的（不走 PowerShell pipeline），
# 所以 `$x = & $renderer` 捕捉不到。做法是暫時把 Console.Out 換成 StringWriter，
# 呼叫完再換回來——這樣完全不必改 usage_statusline.ps1，也保留它被當子行程呼叫時的行為。
function Invoke-Renderer {
    param([string]$Renderer, [string]$Raw)

    $sw  = New-Object System.IO.StringWriter
    $old = [Console]::Out
    try {
        [Console]::SetOut($sw)
        & $Renderer -Raw $Raw | Out-Null
    }
    catch { }
    finally {
        try { [Console]::SetOut($old) } catch { }
    }
    return $sw.ToString()
}

$renderer = Resolve-Renderer
$deadline = (Get-Date).AddHours($MaxHours)

try {
    while ((Get-Date) -lt $deadline) {

        # 心跳：render 路徑靠這個檔的 mtime 判斷「daemon 還活著嗎」
        try { [IO.File]::WriteAllText($beat, (Get-Date).ToString('o')) } catch { }

        # session 是否已結束：injson 由 render 路徑每次刷新覆寫，久沒動＝沒人在看了
        if (-not (Test-Path $injson)) { break }
        try {
            if (((Get-Date) - (Get-Item $injson).LastWriteTime).TotalSeconds -gt $IdleExitSec) { break }
        } catch { break }

        $t0  = [Diagnostics.Stopwatch]::StartNew()
        $raw = ''
        try { $raw = [IO.File]::ReadAllText($injson) } catch { }

        $out = ''
        if ($raw) {
            if ($renderer) {
                $out = Invoke-Renderer -Renderer $renderer -Raw $raw
            }
            else {
                # plugin 找不到時的退路：至少顯示模型名，別讓狀態列空白
                try { $out = ($raw | ConvertFrom-Json).model.display_name } catch { }
            }
        }
        $t0.Stop()

        # 原子寫入：先寫 .tmp 再 move，讓 render 路徑的 cat 永遠讀到完整內容
        if ($out) {
            try {
                [IO.File]::WriteAllText("$cache.tmp", $out)
                Move-Item -Path "$cache.tmp" -Destination $cache -Force
            } catch { }
        }

        # 偵測（預設關）：touch sm_statusline_debug 即開
        if (Test-Path $dbgFlag) {
            $tag = if ($out) { 'OK' } else { 'EMPTY' }
            try {
                Add-Content -Path $dbgLog -Encoding UTF8 -Value (
                    '{0} sid={1} ms={2} bytes={3} {4}' -f
                    (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Sid, $t0.ElapsedMilliseconds, $out.Length, $tag)
            } catch { }
        }

        Start-Sleep -Seconds $IntervalSec
    }
}
finally {
    # 清掉自己的鎖與心跳，讓下一次 render 能乾淨地補起新 daemon
    Remove-Item $lockDir -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item $beat -Force -ErrorAction SilentlyContinue
    # 順手清 1 天前的分艙殘檔（session 結束後不會再被讀，避免無限累積）
    try {
        Get-ChildItem $Base -File -Filter 'sm_statusline_*_*' -ErrorAction SilentlyContinue |
            Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-1) } |
            Remove-Item -Force -ErrorAction SilentlyContinue
    } catch { }
}
