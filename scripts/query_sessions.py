#!/usr/bin/env python3
"""
查詢 session 記憶（由 extract_session.py 累積，按專案分艙）。

  py query_sessions.py "你的問題"                  # BM25 關鍵字檢索最相關的過去 session 摘要
  py query_sessions.py --list                      # 列出庫裡所有 session（peek）
  py query_sessions.py "問題" -k 5                  # 指定回幾筆
  py query_sessions.py "問題" --rel 0.3            # 相對門檻：低於第 1 名分數幾成的不顯示（預設 0.5）
  py query_sessions.py --status                    # 看有沒有 session 還在背景萃取中（沒萃完前查不到）

只查「當前專案」的艙（取自 CLAUDE_PROJECT_DIR，fallback cwd）。

檢索走 BM25：直接讀 summaries/*.md，jieba 斷詞後用 rank_bm25 打分。
BM25 分數沒有上限、不同查詢不能比，所以用「跟第 1 名比」的相對門檻。
繁體詞典 dict.txt.big 與自訂詞 userdict.txt 放在庫根目錄（~/.claude/session-memory/），有就載入。

依賴：pip install chromadb jieba rank_bm25（chromadb 給寫入端與 --list 用）。
"""
import logging
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")          # Windows 主控台預設 cp950，強制 UTF-8 免炸
except Exception:
    pass

from session_mem_common import DB_DIR, DB_ROOT, get_collection

PENDING_DIR = DB_DIR / ".pending"
SUMMARY_DIR = DB_DIR / "summaries"
BIG_DICT = DB_ROOT / "dict.txt.big"
USER_DICT = DB_ROOT / "userdict.txt"

STOPWORDS = set("的 了 是 在 和 與 也 就 都 而 及 或 有 被 把 這 那 個 一 不 要 會 到 跟 給 讓 用 對 為 從 上 下 中 等 嗎 呢 吧 啊".split())
TOKEN_OK = re.compile(r"[\w一-鿿]")
CJK_ONE = re.compile(r"^[一-鿿]$")
# 只有 /clear、/exit 的空 session，主題會寫成這類句子
EMPTY_TOPIC = re.compile(r"無實質|僅含|僅包含|僅有|只執行|只有執行|^無（|^無$")


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


def topic_of(text):
    m = re.search(r"## 主題\s*\n+(.+)", text)
    if m:
        return m.group(1).strip()
    lines = text.splitlines()
    return lines[0].strip() if lines else ""


def load_summaries():
    """讀本專案所有摘要；跳過空 session，同一 session 多份摘要只留最新那份。"""
    docs = {}
    latest = {}
    if not SUMMARY_DIR.exists():
        return docs
    for f in sorted(SUMMARY_DIR.glob("*.md")):
        text = f.read_text(encoding="utf-8", errors="replace")
        if EMPTY_TOPIC.search(topic_of(text)):
            continue
        sid = f.stem.split("_")[-1]
        if sid in latest:
            del docs[latest[sid]]
        latest[sid] = f
        docs[f] = text
    return docs


def get_jieba():
    try:
        import jieba
    except ImportError as e:
        raise RuntimeError("jieba 未安裝 — 跑 /session-memory-setup 或 `pip install jieba rank_bm25`") from e
    jieba.setLogLevel(logging.ERROR)
    if BIG_DICT.exists():
        jieba.set_dictionary(str(BIG_DICT))
    if USER_DICT.exists():
        jieba.load_userdict(str(USER_DICT))
    return jieba


def tokenize(jieba, text):
    tokens = []
    for t in jieba.cut_for_search(text.lower()):
        t = t.strip()
        if not t or t in STOPWORDS or not TOKEN_OK.search(t):
            continue
        # 單一中文字太常見，不計分
        if CJK_ONE.match(t):
            continue
        tokens.append(t)
    return tokens


def cmd_query(q, k=3, rel=0.5):
    warn_pending()
    try:
        from rank_bm25 import BM25Okapi
    except ImportError as e:
        raise RuntimeError("rank_bm25 未安裝 — 跑 /session-memory-setup 或 `pip install jieba rank_bm25`") from e
    docs = load_summaries()
    if not docs:
        print("(還沒有 session 被萃取)")
        return
    jieba = get_jieba()
    files = list(docs)
    bm25 = BM25Okapi([tokenize(jieba, docs[f]) for f in files], k1=1.5, b=0.75)
    q_tokens = tokenize(jieba, q)
    scores = bm25.get_scores(q_tokens)
    ranked = sorted(zip(files, scores), key=lambda x: x[1], reverse=True)
    ranked = [(f, s) for f, s in ranked if s > 0]
    print(f"斷詞：{' / '.join(q_tokens)}")
    if not ranked:
        print("(沒有任何摘要含這些關鍵字 → 換個說法或加中英文同義詞再查)")
        return
    top = ranked[0][1]
    shown = 0
    for f, s in ranked[:k]:
        if s < top * rel:                            # 跟第 1 名差太多就不顯示
            break
        shown += 1
        print(f"\n{'='*64}\n[{shown}] BM25={s:.2f}  ({f})\n{'='*64}")
        print(docs[f][:1500])


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
        k, rel = 3, 0.5
        if "-k" in args:
            i = args.index("-k")
            k = int(args[i + 1])
            args = args[:i] + args[i + 2:]
        if "--rel" in args:
            i = args.index("--rel")
            rel = float(args[i + 1])
            args = args[:i] + args[i + 2:]
        cmd_query(" ".join(args), k, rel)


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as e:                 # 例如 chromadb / jieba / rank_bm25 未安裝
        print(f"⚠ {e}")
        sys.exit(0)
