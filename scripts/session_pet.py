#!/usr/bin/env python3
"""桌寵：session 記憶的視覺指示器（顏文字版）。

右下角 always-on-top 小視窗，可拖曳搬位置。純 cosmetic，掛了不影響任何功能。

== 風格切換 ==
env SM_PET_STYLE=live2d → 改走 Live2D 立繪寵（live2d_pet.py，需 PySide6）：本檔只負責
寫/清標記（.busy/.waiting/.pending 語意不變）+ 確保常駐 daemon 在跑，不開 tkinter 窗。
不設或設 kaomoji（預設）→ 以下顏文字寵邏輯。立繪載不動時 daemon 自己 exit、標記仍在。

兩色系桌寵，明確區隔來源：
  🟢 綠 = 對話一回合（同一隻：作業中 → 處理完成）
  🟡 琥珀 = 等你回應（Claude 停下來等你選擇 / 輸入時）
  🔵 藍 = session 結束萃取記憶（萃取中 → 萃取完成）

== 綠色寵：同一隻，作業中 → 完成（靠 .busy 標記在兩個 hook 進程間傳訊）==
  --busy             UserPromptSubmit hook 用：建 .busy 標記（並清 .waiting）+ detach
                     一隻綠色「作業中…」視窗（盯 .busy）後立刻 return（不阻塞 hook）
  --busy-window      實際顯示動畫；偵測 .waiting 在 → 切琥珀「等你回應 👀」，不在 → 綠
                     「作業中…」；偵測到 .busy 消失即翻成「處理完成 ✓」一閃後自動關
  --done             Stop hook 用：移除 .busy + .waiting → busy 視窗自己翻完成並關。
                     若沒有 busy 視窗在跑（標記不存在）→ fallback 閃一下完成視窗

== 琥珀寵：等你回應（PreToolUse AskUserQuestion hook）==
  --waiting          PreToolUse(AskUserQuestion) 用：建 .waiting 標記。busy 視窗在跑就讓
                     它自己切琥珀；沒在跑才另起一隻 waiting 視窗。
                     （不接 idle/權限 Notification — 只在 Claude 真的丟問題給你選時才橘）
  --waiting-window   琥珀「等你回應 👀」動畫；.waiting 消失即自動關（不翻完成）

== 藍色寵：萃取中 → 完成 ==
  （無參數）  watch  監看當前專案艙 .pending/，顯示藍色「萃取中…」直到萃完

可單獨跑看效果：
  py session_pet.py                 （藍色 watch）
  py session_pet.py --busy-window   （綠色作業中，手動建/刪 .busy / .waiting 看切換）
  py session_pet.py --waiting-window（琥珀等你回應，刪 .waiting 看自動關）
  py session_pet.py --done-window   （綠色完成一閃）
worker 端 env LIFEWIKI_PET=0 可停用萃取中桌寵（綠色寵由 hook 控制，不要就移除該 hook）。
"""
import os
import subprocess
import sys
import time

from session_mem_common import DB_DIR, PLUGIN_VERSION  # 與 worker 同一專案艙（CLAUDE_PROJECT_DIR 由 worker 繼承）

PENDING_DIR = DB_DIR / ".pending"
BUSY_MARKER = DB_DIR / ".busy"      # 綠色寵作業中訊號：UserPromptSubmit 建、Stop 刪
WAITING_MARKER = DB_DIR / ".waiting"  # 琥珀寵等你回應訊號：Notification 建、UserPromptSubmit/Stop 清
MIN_SECONDS = 2.5            # 動畫最短顯示，避免一閃而過
MAX_SECONDS = 20 * 60        # 安全上限，防卡死（hook 沒正常收尾時）
DONE_SECONDS = 2.2           # --done-window 固定一閃秒數
TICK_MS = 450                # 動畫 + 偵測間隔

# 桌寵風格：kaomoji（預設，顏文字 tkinter 寵）| live2d（PySide6 立繪寵）。
# live2d 模式只「寫標記 + 確保常駐 daemon 在跑」，由 live2d_pet.py 讀標記切動作；
# daemon 載不動（缺 PySide6 / 離線 / 模型失敗）會自己 exit 0，標記仍在 → 不影響功能。
PET_STYLE = os.environ.get("SM_PET_STYLE", "kaomoji").strip().lower()

# 配色 (BG, FG, AC)：完成/作業中=綠系，等你回應=琥珀系，萃取中=藍系
GREEN = ("#1b2b22", "#cdf4d6", "#a6e3a1")
AMBER = ("#2b2417", "#f5e6c8", "#e3b341")
BLUE = ("#1e1e2e", "#cdd6f4", "#89b4fa")

FACES = ["(・ω・)", "(・ω・)", "(˘ω˘)", "(・ω・)", "( ・ω・)", "(・ω・ )"]
BARS = ["▱▱▱", "▰▱▱", "▰▰▱", "▰▰▰", "▰▰▱", "▰▱▱"]
WAIT_FACES = ["(・ω・)?", "(・ω・ )?", "( ・ω・)?", "(・ω・)?"]
WAIT_BARS = ["◌ ◌ ◌", "● ◌ ◌", "◌ ● ◌", "◌ ◌ ●"]
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
    is_busy = (mode == "busy-window")        # 綠/琥珀：作業中 ↔ 等你回應 → 完成
    is_wait = (mode == "waiting-window")     # 琥珀：等你回應 → 消失即關
    is_watch = not (is_done or is_busy or is_wait)  # 藍：萃取中 → 完成

    if is_wait:
        BG, FG, AC = AMBER
    elif is_watch:
        BG, FG, AC = BLUE
    else:
        BG, FG, AC = GREEN
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
    elif is_wait:
        first_face, first_msg, first_bar = WAIT_FACES[0], "等你回應 👀", WAIT_BARS[0]
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

    def paint(bg, fg, ac):
        root.configure(bg=bg)
        for wdg in (face, msg, bar):
            wdg.configure(bg=bg)
        face.configure(fg=fg)
        msg.configure(fg=fg)
        bar.configure(fg=ac)

    # 結束條件：busy 盯 .busy；wait 盯 .waiting；watch 盯 pending 清空
    if is_busy:
        done_face, done_msg, done_bar = "(๑˘ᴗ˘๑)b", "處理完成 ✓", DONE_BAR
        # 記住出生時的 .busy token（= 建立它的 --busy 進程 pid）。
        #   .busy 不見    → 正常 Stop 收尾 → 翻「處理完成」
        #   token 變了    → 新一輪 prompt 蓋掉 → 靜默關（涵蓋 ESC 中斷後重送：
        #                   Stop hook 在中斷時不觸發，靠下個 UserPromptSubmit 寫新 token 收掉舊寵）
        my_token = None
        for _ in range(6):
            try:
                my_token = BUSY_MARKER.read_text(encoding="utf-8").strip()
                if my_token:
                    break
            except Exception:
                pass
            time.sleep(0.05)

        def cond_done():
            try:
                cur = BUSY_MARKER.read_text(encoding="utf-8").strip()
            except Exception:
                return True                  # 檔不見 = 正常收尾
            if my_token is None:
                return False                 # 不知自己 token → 退回只靠「檔不見」判斷
            return cur != my_token           # token 變 = 被新回合取代
    elif is_wait:
        done_face = done_msg = done_bar = None   # wait 消失直接關，不翻完成

        def cond_done():
            return not WAITING_MARKER.exists()
    else:
        done_face, done_msg, done_bar = "(๑˘ᴗ˘๑)", "萃取完成 ✓", "▰▰▰"

        def cond_done():
            return pending_count() == 0

    state = {"i": 0}

    def tick():
        i = state["i"]
        # busy 視窗可在「作業中(綠)」與「等你回應(琥珀)」間動態切換
        if is_busy and WAITING_MARKER.exists():
            paint(*AMBER)
            face.config(text=WAIT_FACES[i % len(WAIT_FACES)])
            msg.config(text="等你回應 👀")
            bar.config(text=WAIT_BARS[i % len(WAIT_BARS)])
        elif is_busy:
            paint(*GREEN)
            face.config(text=FACES[i % len(FACES)])
            msg.config(text="作業中…")
            bar.config(text=BARS[i % len(BARS)])
        elif is_wait:
            face.config(text=WAIT_FACES[i % len(WAIT_FACES)])
            bar.config(text=WAIT_BARS[i % len(WAIT_BARS)])
        else:
            face.config(text=FACES[i % len(FACES)])
            bar.config(text=BARS[i % len(BARS)])
        state["i"] += 1
        elapsed = time.time() - start
        finished = cond_done()
        # busy 被新回合取代（檔還在但 token 不同）：靜默關，不假裝完成、不等 MIN_SECONDS
        superseded = is_busy and finished and BUSY_MARKER.exists()
        if superseded or (finished and elapsed >= MIN_SECONDS) or elapsed > MAX_SECONDS:
            if superseded or done_msg is None:   # 取代 / wait：直接關，不翻完成
                root.destroy()
                return
            paint(*GREEN)
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
    _spawn(os.path.abspath(__file__), extra_args)


def _spawn(script, extra_args):
    flags = (0x00000008 | 0x08000000) if os.name == "nt" else 0  # DETACHED | NO_WINDOW
    try:
        subprocess.Popen(
            [sys.executable, script, *extra_args],
            creationflags=flags, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
    except Exception:
        pass                         # cosmetic，失敗不影響任何事


# ============ Live2D 模式：常駐 daemon 啟動（live2d_pet.py 自己讀標記切動作）============
def _live2d_running():
    """daemon 已在跑？Windows 探具名 mutex（輕量、免 import PySide6）；非 Windows 一律 False（讓 daemon 自己用 lockfile 去重）。"""
    if os.name != "nt":
        return False
    try:
        import ctypes
        slug = DB_DIR.name or "default"
        SYNCHRONIZE = 0x00100000
        h = ctypes.windll.kernel32.OpenMutexW(
            SYNCHRONIZE, False, f"Global\\sm_live2d_pet_{slug}_{PLUGIN_VERSION}")
        if h:
            ctypes.windll.kernel32.CloseHandle(h)
            return True
    except Exception:
        pass
    return False


def ensure_live2d():
    """沒在跑就 detach 啟動 Live2D daemon（重複呼叫安全：mutex 探測 + daemon 自帶單例鎖）。"""
    if _live2d_running():
        return
    _spawn(os.path.join(os.path.dirname(os.path.abspath(__file__)), "live2d_pet.py"), [])


def live2d_dispatch(args):
    """live2d 模式的 hook 入口：只動標記 + 確保 daemon 在。標記語意與顏文字版完全相同。"""
    if "--busy" in args:
        try:
            BUSY_MARKER.parent.mkdir(parents=True, exist_ok=True)
            BUSY_MARKER.write_text(str(os.getpid()), encoding="utf-8")
            WAITING_MARKER.unlink(missing_ok=True)
        except Exception:
            pass
        ensure_live2d()
    elif "--waiting" in args:
        try:
            WAITING_MARKER.parent.mkdir(parents=True, exist_ok=True)
            WAITING_MARKER.write_text(str(os.getpid()), encoding="utf-8")
        except Exception:
            pass
        ensure_live2d()
    elif "--unwait" in args:
        try:
            WAITING_MARKER.unlink(missing_ok=True)
        except Exception:
            pass
    elif "--done" in args:
        try:
            BUSY_MARKER.unlink(missing_ok=True)
            WAITING_MARKER.unlink(missing_ok=True)
        except Exception:
            pass
    else:
        ensure_live2d()              # bare：萃取中藍寵 → daemon 讀 .pending 自己顯示


if __name__ == "__main__":
    # 防「萃取也是在跟 Claude 講話」的綠寵誤觸發：extract_session.py 的
    # summarize_claude() 跑巢狀 `claude -p` 時塞了 LIFEWIKI_NO_HOOK=1，那個
    # headless claude 一樣會觸發 hook → 會把綠寵叫出來疊在藍色萃取寵上。
    # 這裡跟 extract_session.py 同款 guard 直接跳過。
    if os.environ.get("LIFEWIKI_NO_HOOK"):
        sys.exit(0)
    args = sys.argv[1:]
    if PET_STYLE == "live2d":            # 立繪寵：改走 daemon + 標記，不開 tkinter 顏文字窗
        live2d_dispatch(args)
        sys.exit(0)
    if "--busy" in args:
        # UserPromptSubmit：建 .busy + 清 .waiting（新回合開始）→ detach 綠色視窗 → return
        try:
            BUSY_MARKER.parent.mkdir(parents=True, exist_ok=True)
            BUSY_MARKER.write_text(str(os.getpid()), encoding="utf-8")
            WAITING_MARKER.unlink(missing_ok=True)
        except Exception:
            pass
        spawn_detached(["--busy-window"])
    elif "--busy-window" in args:
        main(mode="busy-window")
    elif "--waiting" in args:
        # Notification：標記「等你回應」。busy 視窗在跑就讓它自己切琥珀；
        # 沒在跑（idle notification）才另起一隻 waiting 視窗。
        try:
            WAITING_MARKER.parent.mkdir(parents=True, exist_ok=True)
            WAITING_MARKER.write_text(str(os.getpid()), encoding="utf-8")
        except Exception:
            pass
        if not BUSY_MARKER.exists():
            spawn_detached(["--waiting-window"])
    elif "--waiting-window" in args:
        main(mode="waiting-window")
    elif "--unwait" in args:
        # PostToolUse(AskUserQuestion)：用戶答完 → 清「等你回應」→ busy 視窗切回作業中
        try:
            WAITING_MARKER.unlink(missing_ok=True)
        except Exception:
            pass
    elif "--done" in args:
        # Stop：移除 .busy + .waiting → busy 視窗自己翻完成。沒在跑就 fallback 閃一下
        existed = BUSY_MARKER.exists()
        try:
            BUSY_MARKER.unlink(missing_ok=True)
            WAITING_MARKER.unlink(missing_ok=True)
        except Exception:
            pass
        if not existed:
            spawn_detached(["--done-window"])
    elif "--done-window" in args:
        main(mode="done-window")
    else:
        main()
