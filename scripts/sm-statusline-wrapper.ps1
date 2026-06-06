#!/usr/bin/env pwsh
# session-memory plugin — statusLine wrapper（部署到 user space 後使用）
#
# 此檔由 SessionStart hook（deploy_statusline.py）自動複製到 ~/.claude/scripts/。
# 為什麼要這層橋：Claude Code 不會在「user settings.json 的 statusLine 指令」裡展開
# ${CLAUDE_PLUGIN_ROOT}（那變數只在 plugin 自己的 hook/command context 有），而 plugin
# 實際裝在 cache 路徑且含版本號（每次升版就變）。故本檔負責：
#   1. 動態定位 session-memory plugin cache 的「最高版本」目錄
#   2. 把 statusLine 餵進來的 stdin JSON 以 -Raw 原樣轉交 plugin 內 usage_statusline.ps1
# 顯示邏輯全在 plugin 端的 usage_statusline.ps1，隨 /plugin update 一起更新。
$ErrorActionPreference = 'SilentlyContinue'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
$raw = [Console]::In.ReadToEnd()

$base = Join-Path $env:USERPROFILE '.claude\plugins\cache\memory-digest\session-memory'
$target = $null
if (Test-Path $base) {
    $dir = Get-ChildItem $base -Directory |
        Where-Object { $_.Name -match '^\d' } |
        Sort-Object { try { [version]($_.Name) } catch { [version]'0.0.0' } } -Descending |
        Select-Object -First 1
    if ($dir) {
        $cand = Join-Path $dir.FullName 'scripts\usage_statusline.ps1'
        if (Test-Path $cand) { $target = $cand }
    }
}

if ($target) {
    & $target -Raw $raw
}
else {
    # plugin 沒裝 / 找不到：至少顯示模型名，別讓狀態列空白
    try { $d = $raw | ConvertFrom-Json; [Console]::Out.Write($d.model.display_name) } catch { }
}
