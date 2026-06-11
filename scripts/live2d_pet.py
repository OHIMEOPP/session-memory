#!/usr/bin/env python3
"""Live2D 桌寵：session 記憶的視覺指示器（會動的立繪版）。

PySide6 QWebEngineView 撐起一個**透明、無邊框、always-on-top、可拖曳**的小窗，
裡頭 pet.html 用 pixi-live2d-display 跑官方免費模型（Haru Greeter，Cubism 4）。
資源全走 CDN；離線、PySide6 缺、模型載不到 → 一律靜默退出（exit 0），由
session_pet.py 退回顏文字寵。**純 cosmetic，掛了不影響任何記憶功能。**

與顏文字寵不同：這是**一隻常駐窗**，自己輪詢三個標記檔切換動作/表情，
而非每回合 spawn 新窗。hook 機制完全沿用（.busy / .waiting / .pending）。

狀態（優先序）：
  等你回應(.waiting)  → waiting   招手表情 + 字幕「等你回應 👀」
  作業中(.busy)       → busy      idle 動作 + 字幕「作業中…」
  萃取中(.pending/*)  → extracting 思考表情 + 字幕「session 萃取中…」
  剛收尾(busy→無)     → done      開心一閃 ~2s → idle
  其餘                → idle      待機

用法：
  py live2d_pet.py            常駐 watch（讀標記，預設）
  py live2d_pet.py --demo     不讀標記，每 3s 輪播五狀態（看效果用）
環境變數：
  SM_PET_MODEL    覆蓋模型 model3.json URL（預設 Haru Greeter）
  SM_PET_SCALE    模型縮放（預設 0.15）
  SM_PET_CAPTION  0 關閉字幕（預設開）
  SM_PET_IDLE_EXIT  閒置幾分鐘自動關（預設 30；0=永不）
"""
import os
import sys
import time
from pathlib import Path

try:
    from session_mem_common import DB_DIR
except Exception:
    # 獨立執行（不在 plugin 環境）時退回當前目錄，仍可 --demo 看效果
    DB_DIR = Path(os.environ.get("LIFEWIKI_DB_ROOT", Path.home() / ".sm_live2d_demo"))

PENDING_DIR = DB_DIR / ".pending"
BUSY_MARKER = DB_DIR / ".busy"
WAITING_MARKER = DB_DIR / ".waiting"

DEFAULT_MODEL = ("https://cdn.jsdelivr.net/gh/guansss/pixi-live2d-display@master"
                 "/test/assets/haru/haru_greeter_t03.model3.json")
MODEL_URL = os.environ.get("SM_PET_MODEL", DEFAULT_MODEL)
FRAME = os.environ.get("SM_PET_FRAME", "half")        # half 半身 | full 全身 | head 大頭
SCALE = os.environ.get("SM_PET_SCALE", "")            # 給了才覆蓋 frame 自動縮放
CAPTION = "0" if os.environ.get("SM_PET_CAPTION") == "0" else "1"
IDLE_EXIT_MIN = float(os.environ.get("SM_PET_IDLE_EXIT", "30"))

POLL_MS = 500          # 標記輪詢間隔
DONE_HOLD_S = 2.2      # 「處理完成」停留秒數


def pending_count():
    if not PENDING_DIR.exists():
        return 0
    return len(list(PENDING_DIR.glob("*.txt")))


def _single_instance_guard():
    """每個專案艙只准一隻 Live2D 寵。已有就回 False（呼叫端 exit）。

    Windows 具名 mutex：handle 存進模組全域，活到行程結束。非 Windows 退回 lockfile。
    """
    slug = DB_DIR.name or "default"
    if os.name == "nt":
        try:
            import ctypes
            name = f"Global\\sm_live2d_pet_{slug}"
            h = ctypes.windll.kernel32.CreateMutexW(None, False, name)
            if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
                return False
            _single_instance_guard._handle = h   # 防 GC
            return True
        except Exception:
            return True       # 守衛失敗不擋啟動
    # POSIX：簡易 lockfile（pid 存活檢查）
    lock = DB_DIR / ".live2d_pet.lock"
    try:
        if lock.exists():
            pid = int(lock.read_text().strip() or "0")
            if pid > 0:
                try:
                    os.kill(pid, 0)
                    return False          # 還活著
                except OSError:
                    pass                  # 死了，搶鎖
        DB_DIR.mkdir(parents=True, exist_ok=True)
        lock.write_text(str(os.getpid()))
        _single_instance_guard._lock = lock
        return True
    except Exception:
        return True


def main(demo=False):
    def _dbg(m):
        if os.environ.get("SM_PET_DEBUG"):
            try:
                (DB_DIR / "_pet_dbg.log").open("a", encoding="utf-8").write(m + "\n")
            except Exception:
                pass
    _dbg("main start demo=%s pid=%s exe=%s" % (demo, os.getpid(), sys.executable))
    try:
        from PySide6.QtCore import Qt, QUrl, QTimer
        from PySide6.QtWidgets import QApplication, QMainWindow, QWidget
        from PySide6.QtWebEngineWidgets import QWebEngineView
        from PySide6.QtWebEngineCore import QWebEngineSettings
    except Exception as e:
        _dbg("PySide6 import FAIL: %r" % (e,))
        return 0          # 沒 PySide6/WebEngine → 靜默放棄，呼叫端退回顏文字寵
    _dbg("PySide6 import OK")

    if not demo and not _single_instance_guard():
        _dbg("single_instance_guard → already running, exit")
        return 0          # 已有一隻在跑
    _dbg("guard passed")

    app = QApplication.instance() or QApplication(sys.argv)

    # ---- 透明、無邊框、置頂、不進工作列的窗 ----
    win = QMainWindow()
    win.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
    win.setAttribute(Qt.WA_TranslucentBackground, True)
    win.setAttribute(Qt.WA_NoSystemBackground, True)

    container = QWidget(win)
    win.setCentralWidget(container)

    view = QWebEngineView(container)
    view.setAttribute(Qt.WA_TranslucentBackground, True)
    view.page().setBackgroundColor(Qt.transparent)
    s = view.settings()
    WA = QWebEngineSettings.WebAttribute
    s.setAttribute(WA.WebGLEnabled, True)
    s.setAttribute(WA.LocalContentCanAccessRemoteUrls, True)   # file:// 要抓 CDN
    s.setAttribute(WA.LocalContentCanAccessFileUrls, True)
    try:
        s.setAttribute(WA.ShowScrollBars, False)
    except Exception:
        pass

    # ---- 透明拖曳層：蓋在 web view 上，整窗任一處可拖（模型 autoInteract 已關，不搶滑鼠）----
    overlay = QWidget(container)
    overlay.setAttribute(Qt.WA_TranslucentBackground, True)
    overlay.setMouseTracking(True)
    drag = {"off": None}

    def press(e):
        if e.button() == Qt.LeftButton:
            drag["off"] = e.globalPosition().toPoint() - win.frameGeometry().topLeft()

    def move(e):
        if drag["off"] is not None and (e.buttons() & Qt.LeftButton):
            win.move(e.globalPosition().toPoint() - drag["off"])

    def release(e):
        drag["off"] = None

    def dbl(e):           # 雙擊關閉
        win.close()

    overlay.mousePressEvent = press
    overlay.mouseMoveEvent = move
    overlay.mouseReleaseEvent = release
    overlay.mouseDoubleClickEvent = dbl

    def on_resize(e):
        view.setGeometry(0, 0, container.width(), container.height())
        overlay.setGeometry(0, 0, container.width(), container.height())
        overlay.raise_()
    container.resizeEvent = on_resize

    # ---- 載入 pet.html（帶模型 URL 等 query）----
    html = Path(__file__).resolve().parent / "pet_live2d" / "pet.html"
    if not html.exists():
        return 0
    url = QUrl.fromLocalFile(str(html))
    init_state = "idle" if not demo else "busy"
    q = f"model={MODEL_URL}&caption={CAPTION}&frame={FRAME}&state={init_state}"
    if SCALE:
        q += f"&scale={SCALE}"
    url.setQuery(q)
    view.load(url)
    _dbg("view.load done")

    # ---- 視窗大小 / 定位右下角 ----
    W, H = 300, 380
    win.resize(W, H)
    scr = app.primaryScreen().availableGeometry()
    win.move(scr.right() - W - 24, scr.bottom() - H - 16)
    win.show()
    _dbg("win.show done")

    def set_state(st):
        view.page().runJavaScript(
            "window.setPetState && window.setPetState(%r)" % st)

    # ---- 狀態機 ----
    st = {"cur": None, "prev_busy": False, "done_until": 0.0, "last_active": time.time()}

    def resolve():
        now = time.time()
        if demo:
            seq = ["idle", "busy", "waiting", "extracting", "done"]
            return seq[int(now // 3) % len(seq)]
        waiting = WAITING_MARKER.exists()
        busy = BUSY_MARKER.exists()
        pend = pending_count()
        # busy 剛消失（且非等你回應、無萃取）→ done 停留一下
        if st["prev_busy"] and not busy and not waiting and pend == 0:
            st["done_until"] = now + DONE_HOLD_S
        st["prev_busy"] = busy
        if waiting:
            return "waiting"
        if busy:
            return "busy"
        if pend > 0:
            return "extracting"
        if now < st["done_until"]:
            return "done"
        return "idle"

    def tick():
        now = time.time()
        target = resolve()
        if target != st["cur"]:
            st["cur"] = target
            set_state(target)
        # 閒置自動關（demo 不關）
        if target != "idle":
            st["last_active"] = now
        elif IDLE_EXIT_MIN > 0 and not demo:
            if now - st["last_active"] > IDLE_EXIT_MIN * 60:
                win.close()

    timer = QTimer()
    timer.timeout.connect(tick)
    timer.start(POLL_MS)

    _dbg("entering app.exec()")
    rc = app.exec()
    _dbg("app.exec() returned %s" % rc)
    return rc


if __name__ == "__main__":
    # 防萃取時巢狀 claude 觸發 hook 把寵叫出來疊一隻（與 session_pet.py 同款 guard）
    if os.environ.get("LIFEWIKI_NO_HOOK"):
        sys.exit(0)
    sys.exit(main(demo=("--demo" in sys.argv[1:])) or 0)
