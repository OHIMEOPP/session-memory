#!/usr/bin/env python3
"""桌寵：session 記憶的視覺指示器（顏文字版）。

右下角 always-on-top 小視窗，可拖曳搬位置。純 cosmetic，掛了不影響任何功能。

模式：
  （無參數）  watch    — 監看當前專案艙 .pending/，顯示藍色「萃取中…」直到萃完
                         （extract_session.py 的 worker 開始萃取時叫起）
  --done             — 給 Stop hook 用：detach 一個綠色完成視窗後立刻 return（不阻塞 hook）
  --done-window      — 實際顯示綠色「處理完成 ✓」一閃約 DONE_SECONDS 秒後自動關（由 --done 叫起）

可單獨跑看效果：py session_pet.py（watch，無標記時顯示最短秒數後自動關）
              py session_pet.py --done（看完成桌寵）
worker 端 env LIFEWIKI_PET=0 可停用萃取中桌寵（完成桌寵由 Stop hook 控制，不要就移除該 hook）。
"""
import os
import subprocess
import sys
import time

from session_mem_common import DB_DIR        # 與 worker 同一專案艙（CLAUDE_PROJECT_DIR 由 worker 繼承）

PENDING_DIR = DB_DIR / ".pending"
MIN_SECONDS = 2.5            # watch 最短顯示，避免一閃而過
MAX_SECONDS = 20 * 60        # watch 安全上限，防卡死
DONE_SECONDS = 2.2           # --done-window 模式總顯示秒數
TICK_MS = 450                # 動畫 + 偵測間隔

FACES = ["(・ω・)", "(・ω・)", "(˘ω˘)", "(・ω・)", "( ・ω・)", "(・ω・ )"]
BARS = ["▱▱▱", "▰▱▱", "▰▰▱", "▰▰▰", "▰▰▱", "▰▱▱"]


def pending_count():
    if not PENDING_DIR.exists():
        return 0
    return len(list(PENDING_DIR.glob("*.txt")))


def main(mode="watch"):
    try:
        import tkinter as tk
    except Exception:
        return                       # 沒 tkinter 就放棄（不影響任何功能）

    done_mode = (mode == "done-window")
    start = time.time()
    root = tk.Tk()
    root.overrideredirect(True)      # 無標題列
    root.attributes("-topmost", True)
    try:
        root.attributes("-alpha", 0.93)
    except Exception:
        pass

    # 兩種桌寵明顯區隔：完成=綠系，萃取中=藍系
    if done_mode:
        BG, FG, AC = "#1b2b22", "#cdf4d6", "#a6e3a1"     # 完成（綠）
    else:
        BG, FG, AC = "#1e1e2e", "#cdd6f4", "#89b4fa"     # 萃取中（藍）
    root.configure(bg=BG)

    first_face = "(๑˘ᴗ˘๑)b" if done_mode else FACES[0]
    first_msg = "處理完成 ✓" if done_mode else "session 萃取中…"
    first_bar = "✦ ✓ ✦" if done_mode else BARS[0]
    face = tk.Label(root, text=first_face, font=("Segoe UI", 20, "bold"), bg=BG, fg=AC if done_mode else FG)
    face.pack(padx=16, pady=(10, 2))
    msg = tk.Label(root, text=first_msg, font=("Microsoft JhengHei UI", 10), bg=BG, fg=FG)
    msg.pack(padx=16)
    bar = tk.Label(root, text=first_bar, font=("Segoe UI", 13), bg=BG, fg=AC)
    bar.pack(padx=16, pady=(2, 12))

    root.update_idletasks()          # 定位到右下角
    w, h = root.winfo_width(), root.winfo_height()
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(f"+{sw - w - 24}+{sh - h - 72}")

    def start_drag(e):               # 可拖曳
        root._dx, root._dy = e.x, e.y

    def on_drag(e):
        root.geometry(f"+{e.x_root - root._dx}+{e.y_root - root._dy}")

    for wdg in (root, face, msg, bar):
        wdg.bind("<Button-1>", start_drag)
        wdg.bind("<B1-Motion>", on_drag)

    if done_mode:                    # 完成一閃：不監看 pending，定時自動關
        root.after(int(DONE_SECONDS * 1000), root.destroy)
        root.mainloop()
        return

    state = {"i": 0}

    def tick():
        i = state["i"]
        face.config(text=FACES[i % len(FACES)])
        bar.config(text=BARS[i % len(BARS)])
        state["i"] += 1
        elapsed = time.time() - start
        if (pending_count() == 0 and elapsed >= MIN_SECONDS) or elapsed > MAX_SECONDS:
            face.config(text="(๑˘ᴗ˘๑)")
            msg.config(text="萃取完成 ✓")
            bar.config(text="▰▰▰")
            root.after(900, root.destroy)
            return
        root.after(TICK_MS, tick)

    root.after(TICK_MS, tick)
    root.mainloop()


def spawn_detached(extra_args):
    """背景 detach 一份自己（Stop hook 用：叫起視窗後立刻返回，不阻塞）。"""
    flags = (0x00000008 | 0x08000000) if os.name == "nt" else 0  # DETACHED | NO_WINDOW
    try:
        subprocess.Popen(
            [sys.executable, os.path.abspath(__file__), *extra_args],
            creationflags=flags, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
    except Exception:
        pass                         # cosmetic，失敗不影響任何事


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--done" in args:
        spawn_detached(["--done-window"])   # 非阻塞：detach 完成視窗後立刻 return
    elif "--done-window" in args:
        main(mode="done-window")
    else:
        main()
