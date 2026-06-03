#!/usr/bin/env python3
"""
查詢 session 記憶向量庫（由 extract_session.py 累積，按專案分艙）。

  py query_sessions.py "你的問題"                  # 語意檢索最相關的過去 session 摘要
  py query_sessions.py --list                      # 列出庫裡所有 session（peek）
  py query_sessions.py "問題" -k 5                  # 指定回幾筆
  py query_sessions.py "問題" --min-score 0.5      # 只回相似度 ≥ 0.5 的，避免撈到不相關舊紀錄
  py query_sessions.py --status                    # 看有沒有 session 還在背景萃取中（沒萃完前查不到）

只查「當前專案」的艙（取自 CLAUDE_PROJECT_DIR，fallback cwd）。

門檻 (--min-score) 是 query/模型相依的，沒有萬用魔數：建議從 0.45~0.55 起，
看輸出的相似度分數自己校。預設 0.0 = 不過濾。

依賴：pip install chromadb（embedding 後端見 session_mem_common.py；
chroma 模式零 ollama，ollama/openai 模式才需各自依賴）。
"""
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")          # Windows 主控台預設 cp950，強制 UTF-8 免炸
except Exception:
    pass

from session_mem_common import DB_DIR, get_collection

PENDING_DIR = DB_DIR / ".pending"


def pending():
    """回傳目前還在背景萃取中的 session 標記內容清單。"""
    if not PENDING_DIR.exists():
        return []
    return [p.read_text(encoding="utf-8").strip() for p in sorted(PENDING_DIR.glob("*.txt"))]


def warn_pending():
    items = pending()
    if items:
        print(f"⏳ 有 {len(items)} 個 session 還在背景萃取中（萃完才查得到）：")
        for it in items:
            print(f"   - {it}")
        print()


def cmd_status():
    items = pending()
    if not items:
        print("✅ 沒有萃取中的 session（全部已完成）")
    else:
        print(f"⏳ {len(items)} 個 session 萃取中：")
        for it in items:
            print(f"   - {it}")


def cmd_list():
    warn_pending()
    metas = (get_collection().get(include=["metadatas"]).get("metadatas") or [])
    print(f"共 {len(metas)} 個 session：\n")
    for m in sorted(metas, key=lambda x: x.get("ended_at", ""), reverse=True):
        print(f"- {m.get('ended_at','?')} | turns={m.get('turns','?')} "
              f"| reason={m.get('reason','')} | {m.get('summary_file','')}")


def cmd_query(q, k=3, min_score=0.0):
    warn_pending()
    res = get_collection().query(query_texts=[q], n_results=k,    # EF 自動 embed 問題
                                 include=["documents", "metadatas", "distances"])
    docs = res["documents"][0] if res["documents"] else []
    if not docs:
        print("(向量庫是空的，還沒有 session 被萃取)")
        return
    metas, dists = res["metadatas"][0], res["distances"][0]
    shown = 0
    for i, (d, m, dist) in enumerate(zip(docs, metas, dists), 1):
        sim = 1 - dist
        if sim < min_score:                          # 低於門檻直接丟（避免撈到不相關舊紀錄）
            continue
        shown += 1
        print(f"\n{'='*64}\n[{shown}] {m.get('ended_at','?')}  相似度≈{sim:.3f}"
              f"  ({m.get('summary_file','')})\n{'='*64}")
        print(d[:1500])
    if shown == 0:
        top = 1 - dists[0]
        print(f"(沒有相似度 ≥ {min_score} 的過去 session；最高僅 {top:.3f} → 視為不相關，不顯示)")


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return
    if args[0] == "--status":
        cmd_status()
    elif args[0] == "--list":
        cmd_list()
    else:
        k, min_score = 3, 0.0
        if "-k" in args:
            i = args.index("-k")
            k = int(args[i + 1])
            args = args[:i] + args[i + 2:]
        if "--min-score" in args:
            i = args.index("--min-score")
            min_score = float(args[i + 1])
            args = args[:i] + args[i + 2:]
        cmd_query(" ".join(args), k, min_score)


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as e:                 # 例如 chromadb 未安裝（見 session_mem_common._require_chromadb）
        print(f"⚠ {e}")
        sys.exit(0)
