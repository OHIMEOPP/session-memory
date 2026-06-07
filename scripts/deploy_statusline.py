#!/usr/bin/env python3
"""SessionStart hook：把 statusLine wrapper 部署到 user space，並（首次）補上 settings.json。

為什麼要這支：statusLine 無法由 plugin manifest 註冊（Claude Code 只允許 plugin 提供
agent / subagentStatusLine），且 user settings 的 statusLine 指令不展開
${CLAUDE_PLUGIN_ROOT}、plugin cache 路徑又含版本號。故：
  1. 把 plugin 內的 wrapper 模板冪等複製到 ~/.claude/scripts/（隨 /plugin update 更新）
  2. settings.json 沒 statusLine → 補一行指向 wrapper（含 refreshInterval）；已是本 wrapper
     但缺 refreshInterval → 補上該 key；使用者自訂的別的 statusLine → 完全不動

換機 = 裝 plugin 即全自動，免手動。改 settings.json 採保守策略：只在缺 key 時加、保留
其餘設定、atomic 寫回。注意 statusLine 在 session 啟動時載入，本次寫入通常下個 session 生效。
"""
import json
import os
import shutil
from pathlib import Path

WRAPPER_NAME = "sm-statusline-wrapper.ps1"


def deploy_wrapper(root: Path):
    """把 plugin 內 wrapper 冪等複製到 ~/.claude/scripts/，回傳目標路徑（失敗回 None）。"""
    src = root / "scripts" / WRAPPER_NAME
    if not src.exists():
        return None
    dst_dir = Path.home() / ".claude" / "scripts"
    dst = dst_dir / WRAPPER_NAME
    try:
        dst_dir.mkdir(parents=True, exist_ok=True)
        if not dst.exists() or dst.read_bytes() != src.read_bytes():
            shutil.copyfile(src, dst)   # byte-for-byte，保留 UTF-8 BOM
        return dst
    except Exception:
        return None


REFRESH_INTERVAL = 1  # 秒。讓 reset 倒數在 idle 時也每秒跳（倒數顯示到秒，見 usage_statusline.ps1）


def ensure_statusline(wrapper: Path):
    """補/維護 settings.json 的 statusLine。
    - 完全沒有 statusLine → 補一個指向 wrapper、含 refreshInterval 的完整 block。
    - 已有「我們自己的」statusLine（command 指向本 wrapper）但缺 refreshInterval → 補上該 key。
    - 使用者自訂的別的 statusLine（command 不是本 wrapper）→ 完全不動，尊重使用者。
    """
    settings = Path.home() / ".claude" / "settings.json"
    try:
        # utf-8-sig：容忍帶 BOM 的 settings.json（某些編輯器/PowerShell 會寫 BOM），無 BOM 也正常
        data = json.loads(settings.read_text(encoding="utf-8-sig")) if settings.exists() else {}
        if not isinstance(data, dict):
            return
        # 正斜線：Windows 的 sh-like shell 會把反斜線當 escape 吃掉，導致路徑壞、command 靜默失敗
        cmd = "powershell -NoProfile -ExecutionPolicy Bypass -File " + wrapper.as_posix()
        sl = data.get("statusLine")
        changed = False
        if not isinstance(sl, dict):
            data["statusLine"] = {"type": "command", "command": cmd, "refreshInterval": REFRESH_INTERVAL}
            changed = True
        elif WRAPPER_NAME in str(sl.get("command", "")) and "refreshInterval" not in sl:
            sl["refreshInterval"] = REFRESH_INTERVAL
            changed = True
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
    wrapper = deploy_wrapper(Path(root))
    if wrapper:
        ensure_statusline(wrapper)


if __name__ == "__main__":
    main()
