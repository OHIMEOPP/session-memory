#!/usr/bin/env python3
"""SessionStart hook：把 statusLine wrapper 部署到 user space，並（首次）補上 settings.json。

為什麼要這支：statusLine 無法由 plugin manifest 註冊（Claude Code 只允許 plugin 提供
agent / subagentStatusLine），且 user settings 的 statusLine 指令不展開
${CLAUDE_PLUGIN_ROOT}、plugin cache 路徑又含版本號。故：
  1. 冪等部署三支腳本到 ~/.claude/scripts/（隨 /plugin update 更新）：
       - sm-statusline-fast.sh：render 路徑（純 cat 快取，零 PowerShell）
       - sm-statusline-daemon.ps1：背景長駐 refresher（每 session 一個，0.8.5 起）
       - sm-statusline-wrapper.ps1：被當子行程呼叫時的渲染入口（回溯相容）
  2. settings.json 沒 statusLine → 補一行指向 fast.sh（含 refreshInterval）；
     舊版直接呼叫 wrapper.ps1 的 command → 自動遷移成 fast.sh（修狀態列逾時空白 bug）；
     使用者自訂的別的 statusLine → 完全不動。

為什麼要 fast.sh 這層：Claude Code 對 statusLine 指令有逾時，Windows 上 powershell.exe 每次
冷啟 ~0.7-1s 就超時 → 結果被丟棄 → 狀態列空白。把 PowerShell 移出 render 路徑即根治。

換機 = 裝 plugin 即全自動，免手動。改 settings.json 採保守策略：保留其餘設定、atomic 寫回。
注意 statusLine 在 session 啟動時載入，本次寫入通常下個 session 生效。
"""
import json
import os
import shutil
from pathlib import Path

WRAPPER_NAME = "sm-statusline-wrapper.ps1"   # 被當子行程呼叫時的真渲染入口（保留給外部/回溯相容）
DAEMON_NAME = "sm-statusline-daemon.ps1"     # 背景長駐 refresher（0.8.5 起取代 per-refresh spawn）
FAST_NAME = "sm-statusline-fast.sh"          # render 路徑用（純 cat 快取，零 PowerShell）
SCRIPTS_PLACEHOLDER = "__SCRIPTS_DIR__"

SCRIPTS_DIR = Path.home() / ".claude" / "scripts"


def deploy_verbatim(root: Path, name: str):
    """把 plugin 內某支腳本原封不動冪等複製到 ~/.claude/scripts/，回傳目標路徑（失敗回 None）。"""
    src = root / "scripts" / name
    if not src.exists():
        return None
    dst = SCRIPTS_DIR / name
    try:
        SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
        if not dst.exists() or dst.read_bytes() != src.read_bytes():
            shutil.copyfile(src, dst)   # byte-for-byte，保留 UTF-8 BOM
        return dst
    except Exception:
        return None


def deploy_fast(root: Path):
    """把 fast.sh 模板的 __SCRIPTS_DIR__ 替換成實際路徑後冪等部署，回傳目標路徑（失敗回 None）。

    render 路徑與背景 refresh 都把絕對路徑 bake 進去（Windows 磁碟代號 + 正斜線），
    避免 git-bash 的 MSYS 路徑（/c/...）餵給 powershell -File 解析不到。寫 bytes + LF，
    不經 Windows 文字模式換行轉換，免 CRLF 汙染 shebang / 變數。
    """
    src = root / "scripts" / FAST_NAME
    if not src.exists():
        return None
    dst = SCRIPTS_DIR / FAST_NAME
    try:
        SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
        rendered = src.read_text(encoding="utf-8").replace(
            SCRIPTS_PLACEHOLDER, SCRIPTS_DIR.as_posix()
        ).encode("utf-8")
        if not dst.exists() or dst.read_bytes() != rendered:
            dst.write_bytes(rendered)
        return dst
    except Exception:
        return None


REFRESH_INTERVAL = 1  # 秒。讓 reset 倒數在 idle 時也每秒跳（倒數顯示到秒，見 usage_statusline.ps1）


def ensure_statusline(fast: Path):
    """補/維護 settings.json 的 statusLine，指向零延遲的 fast.sh（render 路徑無 PowerShell）。
    - 完全沒有 statusLine → 補一個指向 fast.sh、含 refreshInterval 的完整 block。
    - 舊版「直接呼叫 wrapper.ps1」的 command（含 WRAPPER_NAME 的 powershell 指令）
      → 自動遷移成 fast.sh command（修掉狀態列因逾時空白的 bug）。
    - 已是 fast.sh command → command 不符就校正、缺 refreshInterval 就補。
    - 使用者自訂的別的 statusLine（既非 wrapper 也非 fast）→ 完全不動，尊重使用者。
    """
    settings = Path.home() / ".claude" / "settings.json"
    try:
        # utf-8-sig：容忍帶 BOM 的 settings.json（某些編輯器/PowerShell 會寫 BOM），無 BOM 也正常
        data = json.loads(settings.read_text(encoding="utf-8-sig")) if settings.exists() else {}
        if not isinstance(data, dict):
            return
        # 透過 sh-like shell 跑 bash 腳本；正斜線路徑 bash 與 powershell 皆可吃
        cmd = "bash " + fast.as_posix()
        sl = data.get("statusLine")
        changed = False
        if not isinstance(sl, dict):
            data["statusLine"] = {"type": "command", "command": cmd, "refreshInterval": REFRESH_INTERVAL}
            changed = True
        else:
            curcmd = str(sl.get("command", ""))
            if FAST_NAME in curcmd:
                if sl.get("command") != cmd:        # 路徑/格式校正（例如換機後家目錄不同）
                    sl["command"] = cmd
                    changed = True
                if "refreshInterval" not in sl:
                    sl["refreshInterval"] = REFRESH_INTERVAL
                    changed = True
            elif WRAPPER_NAME in curcmd:             # 舊安裝 → 遷移到 fast 路徑
                sl["type"] = "command"
                sl["command"] = cmd
                if "refreshInterval" not in sl:
                    sl["refreshInterval"] = REFRESH_INTERVAL
                changed = True
            # else：使用者自訂 statusLine，不動
        if not changed:
            return
        tmp = settings.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, settings)       # atomic
    except Exception:
        pass


def main():
    # 萃取的巢狀 claude -p 會帶 LIFEWIKI_NO_HOOK=1 並一樣觸發 SessionStart；跳過避免亂動。
    if os.environ.get("LIFEWIKI_NO_HOOK"):
        return
    root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if not root:
        return
    root = Path(root)
    deploy_verbatim(root, WRAPPER_NAME)   # 子行程呼叫用的渲染入口（回溯相容）
    deploy_verbatim(root, DAEMON_NAME)    # 背景長駐 refresher，由 fast.sh 在心跳過期時補起
    fast = deploy_fast(root)              # render 路徑：純 cat 快取，零 PowerShell
    if fast:
        ensure_statusline(fast)


if __name__ == "__main__":
    main()
