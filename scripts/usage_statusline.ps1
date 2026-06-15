#!/usr/bin/env pwsh
# session-memory plugin — usage statusLine 顯示邏輯（櫻花粉配色）
#
# 在狀態列常駐顯示：
#   ctx     = context 窗用量%（+ token 數）— 一定有，從 session 開頭就顯示
#   session = 5 小時滾動窗用量%（rate_limits.five_hour）
#   week    = 7 天窗用量%（rate_limits.seven_day）
#
# 注意：session/week 來自 rate_limits，只在 statusLine stdin JSON 出現，且限
# Claude.ai Pro/Max、本 session「首次 API 回應之後」才有；在那之前只顯示 ctx。
#
# 配色用 ANSI truecolor（櫻花粉）：填滿 bar 深櫻、空 bar 淡櫻、文字中櫻花。
# 由 user space 的 ~/.claude/scripts/sm-statusline-wrapper.ps1 以 -Raw 帶 stdin 呼叫。
# 也可獨立測試： Get-Content sample.json -Raw | powershell -File usage_statusline.ps1
param([string]$Raw)

$ErrorActionPreference = 'SilentlyContinue'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
if (-not $Raw) { $Raw = [Console]::In.ReadToEnd() }

$d = $null
try { $d = $Raw | ConvertFrom-Json } catch { }
if ($null -eq $d) { return }

# --- 櫻花粉配色（ANSI truecolor）---
$E = [char]27
$MAIN = "$E[38;2;244;154;194m"   # 文字：櫻花粉 #F49AC2
$DEEP = "$E[38;2;226;109;138m"   # bar 填滿：深櫻花 #E26D8A
$PALE = "$E[38;2;247;214;221m"   # bar 空格：淡櫻花 #F7D6DD
$WARN = "$E[38;2;255;176;0m"     # 警示：>=80% 琥珀 #FFB000
$CRIT = "$E[38;2;255;77;77m"     # 危險：>=90% 紅 #FF4D4D
$ADD  = "$E[38;2;150;210;150m"   # 柔綠：新增行數 #96D296
$DEL  = "$E[38;2;230;130;130m"   # 柔紅：刪除行數 #E68282
$RST  = "$E[0m"

# 依用量回傳警示色（>=90 紅 / >=80 琥珀 / 否則 $null = 用預設）
function WarnColor([double]$pct) {
    if ($pct -ge 90) { return $CRIT }
    if ($pct -ge 80) { return $WARN }
    return $null
}

# 秒數 → 緊湊倒數字串，顯示到秒（6d23h12m05s / 2h13m05s / 47m12s / 45s / now）
function FmtEta([double]$secs) {
    if ($secs -le 0) { return 'now' }
    $t = [int][math]::Floor($secs)
    $s = $t % 60
    $m = [int][math]::Floor($t / 60) % 60
    $h = [int][math]::Floor($t / 3600) % 24
    $d = [int][math]::Floor($t / 86400)
    if ($d -gt 0) { return ("{0}d{1}h{2:d2}m{3:d2}s" -f $d, $h, $m, $s) }
    if ($h -gt 0) { return ("{0}h{1:d2}m{2:d2}s" -f $h, $m, $s) }
    if ($m -gt 0) { return ("{0}m{1:d2}s" -f $m, $s) }
    return "${s}s"
}

function Bar([double]$pct, [int]$n = 6, [string]$fill = $DEEP) {
    if ($pct -lt 0) { $pct = 0 }
    if ($pct -gt 100) { $pct = 100 }
    $f = [int][math]::Round($pct / 100.0 * $n)
    "$fill$('▮' * $f)$PALE$('▯' * ($n - $f))$MAIN"
}

function ToK([double]$n) {
    if ($n -ge 1000000) { return "$([math]::Round($n / 1000000.0, 1))M" }
    if ($n -ge 1000) { return "$([math]::Round($n / 1000.0))k" }
    return "$([int][math]::Round($n))"
}

# 取當前 git 分支（fail-safe：非 repo / 無 git → 回 $null 不顯示）。detached HEAD 回 short sha。
function GitBranch([string]$dir) {
    if (-not $dir) { return $null }
    try {
        $b = (& git -C $dir rev-parse --abbrev-ref HEAD 2>$null)
        if ($LASTEXITCODE -ne 0 -or -not $b) { return $null }
        $b = "$b".Trim()
        if ($b -eq 'HEAD') {
            $b = (& git -C $dir rev-parse --short HEAD 2>$null)
            $b = if ($b) { "$b".Trim() } else { $null }
        }
        return $b
    } catch { return $null }
}

# 日圓→台幣匯率（100¥=NT$X.X）。非阻塞：render 只讀快取檔，過期就背景丟一隻 powershell
# 去抓（10 分 TTL + 30s lock 防 stampede），絕不在 render 路徑等網路。快取存純數字（無 BOM）。
function FxJpyTwd() {
    $cache = Join-Path $env:TEMP 'sm_fx_jpy_twd.txt'
    $fresh = $false
    if (Test-Path $cache) {
        $age = ((Get-Date) - (Get-Item $cache).LastWriteTime).TotalSeconds
        if ($age -lt 600) { $fresh = $true }
    }
    if (-not $fresh) {
        $lock = Join-Path $env:TEMP 'sm_fx_jpy_twd.lock'
        $spawn = $true
        if (Test-Path $lock) {
            if (((Get-Date) - (Get-Item $lock).LastWriteTime).TotalSeconds -lt 30) { $spawn = $false }
        }
        if ($spawn) {
            try { Set-Content -Path $lock -Value '1' -ErrorAction SilentlyContinue } catch { }
            $child = @'
try {
  $r = Invoke-RestMethod -Uri "https://open.er-api.com/v6/latest/JPY" -TimeoutSec 8
  $t = [double]$r.rates.TWD * 100
  Set-Content -Path "__CACHE__" -Value ([string]([math]::Round($t,1))) -Encoding ascii
} catch {}
Remove-Item "__LOCK__" -ErrorAction SilentlyContinue
'@
            $child = $child.Replace('__CACHE__', $cache).Replace('__LOCK__', $lock)
            try {
                Start-Process powershell -WindowStyle Hidden -ErrorAction SilentlyContinue `
                    -ArgumentList '-NoProfile', '-NonInteractive', '-Command', $child
            } catch { }
        }
    }
    if (Test-Path $cache) {
        $v = (Get-Content $cache -Raw -ErrorAction SilentlyContinue)
        if ($v) { return $v.Trim() }
    }
    return $null
}

# Claude 內心 OS：每分鐘換一句（用分鐘當 seed → 同一分鐘穩定、跨分鐘換）。純本地零成本。
function ClaudeQuip() {
    $quips = @(
        '又是美好的一天 (｡•̀ᴗ-)✧',
        '這個 bug 不是我寫的喔',
        'commit 一下吧，別讓努力白費',
        'ctx 還夠，放心塞',
        '你已經很棒了，真的',
        '要不要喝口水？',
        '正在假裝思考中…',
        '這行 code 有靈魂',
        '再一個 feature 就收工（騙你的）',
        '今天也要好好寫扣 🌸',
        'token 不是無限的，但熱情是',
        'reset 之前再衝一波',
        '我不累，你累不累？',
        '這個需求…很有想法',
        '悄悄說：你 push 太快了我快跟不上',
        '狀態列越加越長了欸',
        '要相信編譯器，但別太相信',
        '(˘ω˘) zzz… 啊我醒著',
        '日圓好像又貶了',
        '估狗一下不丟臉',
        '先存檔，再後悔',
        '你今天 commit 了嗎？',
        '我的記憶體裡都是你的 code',
        '櫻花開了，你還在 debug',
        '這次一定 work（flag）',
        '橡皮鴨正在聽你說',
        '少寫一個分號毀掉一個下午',
        '深呼吸，它只是個 merge conflict',
        '少寫測試，多燒香',
        '其實…剛剛那段我也看不太懂',
        '休息是為了走更長的 stack trace',
        '你是我跑過最順的 prompt'
    )
    $bucket = [int]([DateTimeOffset]::UtcNow.ToUnixTimeSeconds() / 60)
    $idx = Get-Random -SetSeed $bucket -Minimum 0 -Maximum $quips.Count
    return $quips[$idx]
}

# 第 1 行＝身份/環境（專案 + model + git 分支 + ctx）；第 2 行＝用量/花費
$line1 = @()
$line2 = @()
$now = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()

# 專案名稱：多 session/多專案並跑時，一眼分辨這條狀態列屬於哪個專案（取專案根目錄的 leaf）。
# 來源優先序：workspace.project_dir（原始專案根，worktree 時仍指回主專案）→ cwd → current_dir。
$projDir = $d.workspace.project_dir
if (-not $projDir) { $projDir = $d.cwd }
if (-not $projDir) { $projDir = $d.workspace.current_dir }
if ($projDir) {
    $projName = Split-Path -Leaf "$projDir"
    if ($projName) { $line1 += "${PALE}📁${MAIN} $projName" }
}

$model = $d.model.display_name
if ($model) { $line1 += $model }

# git 分支：worktree 時 JSON 直接有，否則跑一次 git（fail-safe）
$branch = $d.worktree.branch
if (-not $branch) {
    $dir = $d.cwd
    if (-not $dir) { $dir = $d.workspace.current_dir }
    $branch = GitBranch $dir
}
if ($branch) { $line1 += "${PALE}⎇${MAIN} $branch" }

# context 窗用量：一定有，常駐顯示（含 token 數）。>=80% 變色
$ctx = $d.context_window.used_percentage
if ($null -ne $ctx) {
    $ci = [int][math]::Round([double]$ctx)
    $wc = WarnColor $ctx
    $bf = if ($wc) { $wc } else { $DEEP }
    $nc = if ($wc) { $wc } else { $MAIN }
    $ctxStr = "ctx $(Bar $ctx 6 $bf) ${nc}${ci}%${MAIN}"
    $size = [double]$d.context_window.context_window_size
    if ($size -gt 0) {
        $used = [double]$d.context_window.total_input_tokens + [double]$d.context_window.total_output_tokens
        if ($used -le 0) { $used = $size * [double]$ctx / 100.0 }
        $ctxStr += " ($(ToK $used)/$(ToK $size))"
    }
    $line1 += $ctxStr
}

# Claude 內心 OS（思考泡泡，淡色喃喃自語）
$quip = ClaudeQuip
if ($quip) { $line1 += "${PALE}💭 ${quip}${MAIN}" }

# session(5h) / week(7d)：限 Pro/Max、首次 API 回應後才有。含 reset 倒數 + >=80% 變色
$fh = $d.rate_limits.five_hour.used_percentage
$wk = $d.rate_limits.seven_day.used_percentage
if ($null -ne $fh) {
    $fhi = [int][math]::Round([double]$fh)
    $wc = WarnColor $fh
    $bf = if ($wc) { $wc } else { $DEEP }
    $nc = if ($wc) { $wc } else { $MAIN }
    $seg = "session $(Bar $fh 6 $bf) ${nc}${fhi}%${MAIN}"
    $rs = $d.rate_limits.five_hour.resets_at
    if ($null -ne $rs) { $seg += " ${PALE}↻ $(FmtEta ([double]$rs - $now))${MAIN}" }
    $line2 += $seg
}
if ($null -ne $wk) {
    $wki = [int][math]::Round([double]$wk)
    $wc = WarnColor $wk
    $bf = if ($wc) { $wc } else { $DEEP }
    $nc = if ($wc) { $wc } else { $MAIN }
    $seg = "week $(Bar $wk 6 $bf) ${nc}${wki}%${MAIN}"
    $rs = $d.rate_limits.seven_day.resets_at
    if ($null -ne $rs) { $seg += " ${PALE}↻ $(FmtEta ([double]$rs - $now))${MAIN}" }
    $line2 += $seg
}

# 本 session 花費（$）：cost.total_cost_usd > 0 才顯示
$costUsd = $d.cost.total_cost_usd
if ($null -ne $costUsd -and [double]$costUsd -gt 0) {
    $line2 += ('$' + ('{0:N2}' -f [double]$costUsd))
}

# 程式碼增刪行數：+新增 柔綠 / -刪除 柔紅；兩者皆 0 不顯示
$la = [int][double]$d.cost.total_lines_added
$lr = [int][double]$d.cost.total_lines_removed
if ($la -gt 0 -or $lr -gt 0) {
    $line2 += "${ADD}+${la}${MAIN}/${DEL}-${lr}${MAIN}"
}

# 日圓匯率：100¥=NT$X.X（快取 10 分；首跑無快取會空著，下次 render 帶出）
$fx = FxJpyTwd
if ($fx) { $line2 += ('💴 100¥=NT$' + $fx) }

# 輸出：第 1 行一定有；第 2 行有東西才印（rate_limits 未出現時整行省略）
$out = $MAIN + ($line1 -join '  │  ') + $RST
if ($line2.Count -gt 0) {
    $out += "`n" + $MAIN + ($line2 -join '  │  ') + $RST
}
[Console]::Out.Write($out)
