#!/usr/bin/env python3
"""桌寵：session 記憶的視覺指示器（顏文字版）。

右下角 always-on-top 小視窗，可拖曳搬位置。純 cosmetic，掛了不影響任何功能。

兩色系桌寵，明確區隔來源：
  🟢 綠 = 對話一回合（同一隻：作業中 → 處理完成）
  🔵 藍 = session 結束萃取記憶（萃取中 → 萃取完成）

== 綠色寵：同一隻，作業中 → 完成（靠 .busy 標記在兩個 hook 進程間傳訊）==
  --busy             UserPromptSubmit hook 用：建 .busy 標記 + detach 一隻綠色
                     「作業中…」視窗（盯 .busy）後立刻 return（不阻塞 hook）
  --busy-window      實際顯示綠色「作業中…」動畫；偵測到 .busy 消失即翻成
                     「處理完成 ✓」一閃後自動關（由 --busy 叫起）
  --done             Stop hook 用：移除 .busy → 那隻 busy 視窗自己翻成完成並關。
                     若沒有 busy 視窗在跑（標記不存在）→ fallback 閃一下完成視窗
  --done-window      綠色「處理完成 ✓」固定一閃 DONE_SECONDS 秒（fallback 用）

== 藍色寵：萃取中 → 完成 ==
  （無參數）  watch  監看當前專案艙 .pending/，顯示藍色「萃取中…」直到萃完
                     （extract_session.py 的 worker 開始萃取時叫起）

可單獨跑看效果：
  py session_pet.py            （藍色 watch）
  py session_pet.py --busy-window   （綠色作業中，需手動建/刪 .busy 看翻完成）
  py session_pet.py --done-window   （綠色完成一閃）
worker 端 env LIFEWIKI_PET=0 可停用萃取中桌寵（綠色寵由 UserPromptSubmit/Stop hook 控制，不要就移除該 hook）。
"""
import os
import subprocess
import sys
import time

from session_mem_common import DB_DIR        # 與 worker 同一專案艙（CLAUDE_PROJECT_DIR 由 worker 繼承）

PENDING_DIR = DB_DIR / ".pending"
BUSY_MARKER = DB_DIR / ".busy"      # 綠色寵作業中訊號：UserPromptSubmit 建、Stop 刪
MIN_SECONDS = 2.5            # 動畫最短顯示，避免一閃而過
MAX_SECONDS = 20 * 60        # 安全上限，防卡死（hook 沒正常收尾時）
DONE_SECONDS = 2.2           # --done-window 固定一閃秒數
TICK_MS = 450                # 動畫 + 偵測間隔

# 配色：完成/作業中=綠系，萃取中=藍系
GREEN = ("#1b2b22", "#cdf4d6", "#a6e3a1")
BLUE = ("#1e1e2e", "#cdd6f4", "#89b4fa")

FACES = ["(・ω・)", "(・ω・)", "(˘ω˘)", "(・ω・)", "( ・ω・)", "(・ω・ )"]
BARS = ["▱▱▱", "▰▱▱", "▰▰▱", "▰▰▰", "▰▰▱", "▰▱▱"]
DONE_BAR = "✦ ✓ ✦"


def pending_count():
    if not PENDING_DIR.exists():
        return 0
    return len(list(PENDING_DIR.glob("*.txt")))


def main(mode="watch"):
    try:
        import tkinter as tk
    except Exception:
        return                       # 沒 tkinter 就放棄（不影響任何功能）

    is_done = (mode == "done-window")        # 綠：固定一閃
    is_busy = (mode == "busy-window")        # 綠：作業中 → 完成
    is_watch = not (is_done or is_busy)      # 藍：萃取中 → 完成

    BG, FG, AC = GREEN if (is_done or is_busy) else BLUE
    start = time.time()
    root = tk.Tk()
    root.overrideredirect(True)      # 無標題列
    root.attributes("-topmost", True)
    try:
        root.attributes("-alpha", 0.93)
    except Exception:
        pass
    root.configure(bg=BG)

    if is_done:
        first_face, first_msg, first_bar = "(๑˘ᴗ˘๑)b", "處理完成 ✓", DONE_BAR
    elif is_busy:
        first_face, first_msg, first_bar = FACES[0], "作業中…", BARS[0]
    else:
        first_face, first_msg, first_bar = FACES[0], "session 萃取中…", BARS[0]

    face = tk.Label(root, text=first_face, font=("Segoe UI", 20, "bold"),
                    bg=BG, fg=AC if is_done else FG)
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

    if is_done:                      # 完成一閃：不監看，定時自動關
        root.after(int(DONE_SECONDS * 1000), root.destroy)
        root.mainloop()
        return

    # 動畫模式：busy（綠，盯 .busy 消失）與 watch（藍，盯 pending 清空）
    if is_busy:
        done_face, done_msg, done_bar = "(๑˘ᴗ˘๑)b", "處理完成 ✓", DONE_BAR

        def cond_done():
            return not BUSY_MARKER.exists()
    else:
        done_face, done_msg, done_bar = "(๑˘ᴗ˘๑)", "萃取完成 ✓", "▰▰▰"

        def cond_done():
            return pending_count() == 0

    state = {"i": 0}

    def tick():
        i = state["i"]
        face.config(text=FACES[i % len(FACES)])
        bar.config(text=BARS[i % len(BARS)])
        state["i"] += 1
        elapsed = time.time() - start
        if (cond_done() and elapsed >= MIN_SECONDS) or elapsed > MAX_SECONDS:
            face.config(text=done_face, fg=AC)
            msg.config(text=done_msg)
            bar.config(text=done_bar)
            root.after(900, root.destroy)
            return
        root.after(TICK_MS, tick)

    root.after(TICK_MS, tick)
    root.mainloop()


def spawn_detached(extra_args):
    """背景 detach 一份自己（hook 用：叫起視窗後立刻返回，不阻塞）。"""
    flags = (0x00000008 | 0x08000000) if os.name == "nt" else 0  # DETACHED | NO_WINDOW
    try:
        subprocess.Popen(
            [sys.executable, os.path.abspath(__file__), *extra_args],
            creationflags=flags, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
    except Exception:
        pass                         # cosmetic，失敗不影響任何事


if __name__ == "__main__":
    # 防「萃取也是在跟 Claude 講話」的綠寵誤觸發：extract_session.py 的
    # summarize_claude() 跑巢狀 `claude -p` 時塞了 LIFEWIKI_NO_HOOK=1，那個
    # headless claude 一樣會觸發 UserPromptSubmit/Stop hook → 會把綠寵叫出來
    # 疊在藍色萃取寵上。這裡跟 extract_session.py 同款 guard 直接跳過。
    # （藍色萃取寵不受影響：它由 worker 直接 spawn，env 沒這個 flag。）
    if os.environ.get("LIFEWIKI_NO_HOOK"):
        sys.exit(0)
    args = sys.argv[1:]
    if "--busy" in args:
        # UserPromptSubmit：建標記 → detach 綠色作業中視窗 → 立刻 return
        try:
            BUSY_MARKER.parent.mkdir(parents=True, exist_ok=True)
            BUSY_MARKER.write_text(str(os.getpid()), encoding="utf-8")
        except Exception:
            pass
        spawn_detached(["--busy-window"])
    elif "--busy-window" in args:
        main(mode="busy-window")
    elif "--done" in args:
        # Stop：移除標記 → busy 視窗自己翻成完成。沒 busy 視窗在跑就 fallback 閃一下
        existed = BUSY_MARKER.exists()
        try:
            BUSY_MARKER.unlink()
        except Exception:
            pass
        if not existed:
            spawn_detached(["--done-window"])
    elif "--done-window" in args:
        main(mode="done-window")
    else:
        main()
