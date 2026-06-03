#!/usr/bin/env python3
"""桌寵：session 萃取中的視覺指示器（顏文字版）。

右下角 always-on-top 小視窗，動態顏文字 + 進度條 +「session 萃取中…」。
偵測當前專案艙的 .pending/ 還有沒有標記：沒了（萃完）就自動收尾關閉。
由 extract_session.py 的 worker 在開始萃取時叫起；純 cosmetic，掛了不影響萃取。

可單獨跑看效果：py session_pet.py（無標記時顯示最短秒數後自動關）。
可拖曳搬位置。worker 端 env LIFEWIKI_PET=0 可停用。
"""
import time

from session_mem_common import DB_DIR        # 與 worker 同一專案艙（CLAUDE_PROJECT_DIR 由 worker 繼承）

PENDING_DIR = DB_DIR / ".pending"
MIN_SECONDS = 2.5            # 最短顯示，避免一閃而過
MAX_SECONDS = 20 * 60        # 安全上限，防卡死
TICK_MS = 450                # 動畫 + 偵測間隔

FACES = ["(・ω・)", "(・ω・)", "(˘ω˘)", "(・ω・)", "( ・ω・)", "(・ω・ )"]
BARS = ["▱▱▱", "▰▱▱", "▰▰▱", "▰▰▰", "▰▰▱", "▰▱▱"]


def pending_count():
    if not PENDING_DIR.exists():
        return 0
    return len(list(PENDING_DIR.glob("*.txt")))


def main():
    try:
        import tkinter as tk
    except Exception:
        return                       # 沒 tkinter 就放棄（不影響萃取）

    start = time.time()
    root = tk.Tk()
    root.overrideredirect(True)      # 無標題列
    root.attributes("-topmost", True)
    try:
        root.attributes("-alpha", 0.93)
    except Exception:
        pass
    BG, FG, AC = "#1e1e2e", "#cdd6f4", "#89b4fa"
    root.configure(bg=BG)

    face = tk.Label(root, text=FACES[0], font=("Segoe UI", 20, "bold"), bg=BG, fg=FG)
    face.pack(padx=16, pady=(10, 2))
    msg = tk.Label(root, text="session 萃取中…", font=("Microsoft JhengHei UI", 10), bg=BG, fg=FG)
    msg.pack(padx=16)
    bar = tk.Label(root, text=BARS[0], font=("Segoe UI", 13), bg=BG, fg=AC)
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


if __name__ == "__main__":
    main()
