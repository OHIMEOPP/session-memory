#!/usr/bin/env pwsh
# session-memory plugin — usage statusLine 顯示邏輯
#
# 在狀態列常駐顯示 /usage 的兩個關鍵數字：
#   session = 5 小時滾動窗用量%（rate_limits.five_hour）
#   week    = 7 天窗用量%（rate_limits.seven_day）
# 外加 context 窗用量當保底。
#
# 注意：rate_limits 只在 statusLine stdin JSON 出現，且限 Claude.ai Pro/Max、
# 本 session「首次 API 回應之後」才有；其餘情況退回顯示 context 窗用量。
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

$parts = @()

$model = $d.model.display_name
if ($model) { $parts += $model }

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

# rate_limits 都還沒 ready（剛開 session / 非 Pro·Max）→ 退回 context 窗用量
if ($null -eq $fh -and $null -eq $wk) {
    $ctx = $d.context_window.used_percentage
    if ($null -ne $ctx) {
        $ci = [int][math]::Round([double]$ctx)
        $parts += "ctx $(Bar $ctx) ${ci}% (rate 待首次回應)"
    }
}

[Console]::Out.Write(($parts -join '  │  '))
