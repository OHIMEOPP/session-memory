#!/usr/bin/env python3
"""
SessionEnd hook：智慧式萃取本 session → Markdown 摘要 → 存進 Chroma 向量庫。

兩種模式：
  (1) 無參數 = hook 入口：讀 stdin 的 hook payload，立刻 spawn 一個 detached
      worker 跑重活，然後馬上 exit 0（不卡 /exit、/clear）。
  (2) --run <transcript> <session_id> <reason> = worker：萃取 + embed + 存。

萃取後端：claude -p（主）→ 失敗 fallback Ollama qwen3.5（env LIFEWIKI_EXTRACT_BACKEND 可切）。
向量庫：Chroma persistent，按專案分艙（~/.claude/session-memory/<專案-slug>/，見 session_mem_common.py）。

全程 try/except + log，絕不讓 hook 失敗影響使用者退出。

依賴：pip install chromadb（embedding 後端見 session_mem_common.py，預設 chroma 零 ollama）。
萃取後端 claude 走 CLI；fallback=ollama 才需 `pip install ollama` + 模型。
"""
import sys
import os
import json
import subprocess
import datetime
import traceback
from pathlib import Path

from session_mem_common import DB_DIR        # 本專案專屬向量庫（按 CLAUDE_PROJECT_DIR 分艙）

ROOT = Path(__file__).resolve().parent        # scripts/（腳本所在；spawn session_pet.py 用）
SUMMARY_DIR = DB_DIR / "summaries"
PENDING_DIR = DB_DIR / ".pending"             # 萃取中標記（worker 跑完才刪），供 query 顯示進度
LOG = DB_DIR / "extract.log"

EXTRACT_BACKEND = os.environ.get("LIFEWIKI_EXTRACT_BACKEND", "claude")  # claude | ollama
OLLAMA_LLM = os.environ.get("LIFEWIKI_OLLAMA_LLM", "qwen3.5:9b")
# embedding 後端見 session_mem_common.py（LIFEWIKI_EMBED_BACKEND，預設 chroma）

SUMMARY_INSTRUCTION = """你是知識庫的 session 萃取器。下面是一段 Claude Code 的工作 session 對話記錄。
請萃取成繁體中文摘要，只保留對「下一個 session 接手」有價值的高訊號內容，丟棄過程噪音。
用以下 Markdown 結構輸出（某段沒有就寫「無」）：

## 主題
一句話這次在做什麼。

## 關鍵決策（含理由）
- 決策 — 為什麼這樣決定

## 產出 / 變更
- 動到的檔案、commit、artifact

## 開放問題 / 待辦
- 還沒做完、或待 user 決定的事

## 重要事實 / 踩坑
- 之後會重複用到的事實、踩過的坑與解法

只輸出 Markdown，不要任何前言或結語。"""


def log(msg):
    try:
        DB_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().isoformat(timespec="seconds")
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


def read_conversation(transcript_path):
    """從 Claude Code transcript JSONL 萃出人讀對話文字 + 對話輪數。"""
    out = []
    turns = 0
    with open(transcript_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except Exception:
                continue
            typ = ev.get("type")
            if typ not in ("user", "assistant"):
                continue
            content = (ev.get("message") or {}).get("content")
            text = ""
            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                parts = []
                for b in content:
                    if not isinstance(b, dict):
                        continue
                    bt = b.get("type")
                    if bt == "text":
                        parts.append(b.get("text", ""))
                    elif bt == "tool_use":
                        parts.append(f"[tool_use: {b.get('name', '')}]")
                    elif bt == "tool_result":
                        parts.append("[tool_result]")        # 工具結果通常很長，只記有用過
                text = "\n".join(p for p in parts if p)
            text = (text or "").strip()
            if not text:
                continue
            role = "使用者" if typ == "user" else "Claude"
            out.append(f"### {role}\n{text}")
            turns += 1
    return "\n\n".join(out), turns


def summarize_claude(convo):
    convo = convo[:500000]                                   # Claude 1M context，留餘裕
    env = {**os.environ, "LIFEWIKI_NO_HOOK": "1"}            # 防 headless claude 的 SessionEnd 遞迴
    flags = 0x08000000 if os.name == "nt" else 0            # CREATE_NO_WINDOW：不彈出黑 console 視窗
    r = subprocess.run(
        ["claude", "-p", SUMMARY_INSTRUCTION],
        input=convo, capture_output=True, text=True,
        encoding="utf-8", env=env, timeout=600, creationflags=flags,
    )
    if r.returncode != 0 or not (r.stdout or "").strip():
        raise RuntimeError(f"claude -p rc={r.returncode} err={(r.stderr or '')[:300]}")
    return r.stdout.strip()


def summarize_ollama(convo):
    import ollama
    convo = convo[-24000:]                                   # qwen 視窗有限，留最近段
    r = ollama.chat(model=OLLAMA_LLM, messages=[
        {"role": "system", "content": SUMMARY_INSTRUCTION},
        {"role": "user", "content": convo},
    ], options={"temperature": 0.2})
    return r["message"]["content"].strip()


def summarize(convo):
    order = ["claude", "ollama"] if EXTRACT_BACKEND == "claude" else ["ollama", "claude"]
    last = None
    for backend in order:
        try:
            return (summarize_claude(convo) if backend == "claude"
                    else summarize_ollama(convo)), backend
        except Exception as e:
            last = e
            log(f"summarize backend={backend} failed: {e}")
    raise RuntimeError(f"all summarize backends failed: {last}")


def store(summary, meta):
    from session_mem_common import get_collection
    col = get_collection()                                # embedding_function 會自動 embed document
    col.upsert(ids=[meta["id"]], documents=[summary], metadatas=[meta])


def run_worker(transcript_path, session_id, reason):
    marker = None
    try:
        if not transcript_path or not os.path.exists(transcript_path):
            log(f"worker: transcript missing {transcript_path}")
            return
        convo, turns = read_conversation(transcript_path)
        if turns < 2 or len(convo) < 200:
            log(f"skip: too short (turns={turns}, len={len(convo)}) sid={session_id}")
            return
        sid8 = (session_id or "unknown")[:8]
        start = datetime.datetime.now()
        PENDING_DIR.mkdir(parents=True, exist_ok=True)        # 放「萃取中」標記
        marker = PENDING_DIR / f"{start:%Y%m%d_%H%M%S}_{sid8}.txt"
        marker.write_text(
            f"session={session_id} started={start.isoformat(timespec='seconds')} turns={turns}",
            encoding="utf-8")
        if os.environ.get("LIFEWIKI_PET", "1") != "0":      # 叫出桌寵（cosmetic，失敗不影響萃取）
            try:
                petflags = (0x00000008 | 0x08000000) if os.name == "nt" else 0
                subprocess.Popen(
                    [sys.executable, str(ROOT / "session_pet.py")],
                    creationflags=petflags, stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
            except Exception as e:
                log(f"pet spawn failed: {e}")
        summary, used = summarize(convo)
        now = datetime.datetime.now()
        SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
        md_path = SUMMARY_DIR / f"{now:%Y%m%d_%H%M}_{sid8}.md"
        header = (f"# Session {sid8} — {now:%Y-%m-%d %H:%M}\n"
                  f"_reason={reason} · turns={turns} · extractor={used}_\n\n")
        md_path.write_text(header + summary, encoding="utf-8")
        meta = {
            "id": f"{now:%Y%m%d_%H%M%S}_{sid8}",
            "session_id": session_id or "",
            "ended_at": now.isoformat(timespec="seconds"),
            "reason": reason or "",
            "turns": turns,
            "extractor": used,
            "summary_file": str(md_path),
        }
        store(summary, meta)
        log(f"OK stored sid={sid8} turns={turns} extractor={used} -> {md_path.name}")
    except Exception as e:
        log(f"worker ERROR sid={session_id}: {e}\n{traceback.format_exc()}")
    finally:
        try:
            if marker and marker.exists():
                marker.unlink()                               # 萃取結束（成功或失敗）→ 清掉「萃取中」標記
        except Exception:
            pass


def main():
    if os.environ.get("LIFEWIKI_NO_HOOK"):                   # 防遞迴：headless claude 跳過
        sys.exit(0)

    # worker 模式
    if len(sys.argv) >= 5 and sys.argv[1] == "--run":
        run_worker(sys.argv[2], sys.argv[3], sys.argv[4])
        return

    # hook 入口：讀 payload → spawn detached worker → 立刻退出
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    tpath = payload.get("transcript_path", "")
    sid = payload.get("session_id", "")
    reason = payload.get("reason", "")
    if not tpath or not os.path.exists(tpath):
        log(f"hook: no transcript ({tpath}) reason={reason}")
        sys.exit(0)

    flags = (0x00000008 | 0x08000000) if os.name == "nt" else 0   # DETACHED_PROCESS | CREATE_NO_WINDOW
    try:
        subprocess.Popen(
            [sys.executable, os.path.abspath(__file__), "--run", tpath, sid, reason],
            creationflags=flags,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            close_fds=True,
        )
    except Exception as e:
        log(f"hook: spawn failed: {e}")
    sys.exit(0)


if __name__ == "__main__":
    main()
