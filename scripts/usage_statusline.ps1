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
$RST  = "$E[0m"

# 依用量回傳警示色（>=90 紅 / >=80 琥珀 / 否則 $null = 用預設）
function WarnColor([double]$pct) {
    if ($pct -ge 90) { return $CRIT }
    if ($pct -ge 80) { return $WARN }
    return $null
}

# 秒數 → 緊湊倒數字串（2h13m / 47m / 3d4h / now）
function FmtEta([double]$secs) {
    if ($secs -le 0) { return 'now' }
    $m = [int][math]::Floor($secs / 60)
    if ($m -lt 60) { return "${m}m" }
    $h = [int][math]::Floor($m / 60); $mm = $m % 60
    if ($h -lt 24) { return "${h}h${mm}m" }
    $dd = [int][math]::Floor($h / 24); $hh = $h % 24
    return "${dd}d${hh}h"
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

$parts = @()
$now = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()

$model = $d.model.display_name
if ($model) { $parts += $model }

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
    $parts += $ctxStr
}

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
    if ($null -ne $rs) { $seg += " ${PALE}↻$(FmtEta ([double]$rs - $now))${MAIN}" }
    $parts += $seg
}
if ($null -ne $wk) {
    $wki = [int][math]::Round([double]$wk)
    $wc = WarnColor $wk
    $bf = if ($wc) { $wc } else { $DEEP }
    $nc = if ($wc) { $wc } else { $MAIN }
    $seg = "week $(Bar $wk 6 $bf) ${nc}${wki}%${MAIN}"
    $rs = $d.rate_limits.seven_day.resets_at
    if ($null -ne $rs) { $seg += " ${PALE}↻$(FmtEta ([double]$rs - $now))${MAIN}" }
    $parts += $seg
}

[Console]::Out.Write($MAIN + ($parts -join '  │  ') + $RST)
