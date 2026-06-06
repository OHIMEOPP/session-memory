#!/usr/bin/env pwsh
# session-memory plugin — usage statusLine 顯示邏輯
#
# 在狀態列常駐顯示：
#   ctx     = context 窗用量%（+ token 數）— 一定有，從 session 開頭就顯示
#   session = 5 小時滾動窗用量%（rate_limits.five_hour）
#   week    = 7 天窗用量%（rate_limits.seven_day）
#
# 注意：session/week 來自 rate_limits，只在 statusLine stdin JSON 出現，且限
# Claude.ai Pro/Max、本 session「首次 API 回應之後」才有；在那之前只顯示 ctx。
#
# 由 user space 的 ~/.claude/scripts/sm-statusline-wrapper.ps1 以 -Raw 帶 stdin 呼叫
# （statusLine 不展開 ${CLAUDE_PLUGIN_ROOT}，故需 wrapper 動態定位本檔）。
# 也可獨立測試： Get-Content sample.json -Raw | powershell -File usage_statusline.ps1
param([string]$Raw)

$ErrorActionPreference = 'SilentlyContinue'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
if (-not $Raw) { $Raw = [Console]::In.ReadToEnd() }

$d = $null
try { $d = $Raw | ConvertFrom-Json } catch { }
if ($null -eq $d) { return }

function Bar([double]$pct, [int]$n = 6) {
    if ($pct -lt 0) { $pct = 0 }
    if ($pct -gt 100) { $pct = 100 }
    $fill = [int][math]::Round($pct / 100.0 * $n)
    ('▮' * $fill) + ('▯' * ($n - $fill))
}

function ToK([double]$n) {
    if ($n -ge 1000000) { return "$([math]::Round($n / 1000000.0, 1))M" }
    if ($n -ge 1000) { return "$([math]::Round($n / 1000.0))k" }
    return "$([int][math]::Round($n))"
}

$parts = @()

$model = $d.model.display_name
if ($model) { $parts += $model }

# context 窗用量：一定有，常駐顯示（含 token 數）
$ctx = $d.context_window.used_percentage
if ($null -ne $ctx) {
    $ci = [int][math]::Round([double]$ctx)
    $ctxStr = "ctx $(Bar $ctx) ${ci}%"
    $size = [double]$d.context_window.context_window_size
    if ($size -gt 0) {
        $used = [double]$d.context_window.total_input_tokens + [double]$d.context_window.total_output_tokens
        if ($used -le 0) { $used = $size * [double]$ctx / 100.0 }
        $ctxStr += " ($(ToK $used)/$(ToK $size))"
    }
    $parts += $ctxStr
}

# session(5h) / week(7d)：限 Pro/Max、首次 API 回應後才有
$fh = $d.rate_limits.five_hour.used_percentage
$wk = $d.rate_limits.seven_day.used_percentage
if ($null -ne $fh) {
    $fhi = [int][math]::Round([double]$fh)
    $parts += "session $(Bar $fh) ${fhi}%"
}
if ($null -ne $wk) {
    $wki = [int][math]::Round([double]$wk)
    $parts += "week $(Bar $wk) ${wki}%"
}

[Console]::Out.Write(($parts -join '  │  '))
