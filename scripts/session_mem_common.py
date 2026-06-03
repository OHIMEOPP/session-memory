#!/usr/bin/env python3
"""共用：session 記憶向量庫的 embedding 後端與 collection 取得。

extract_session.py（寫入）與 query_sessions.py（查詢）都從這裡拿 collection，
確保兩端用**同一個 embedding 後端**——store 與 query 若用不同 embedding 空間，
語意比對會全錯、查不到。

embedding 後端（env `LIFEWIKI_EMBED_BACKEND`，預設 chroma）：
  chroma  — Chroma 內建 MiniLM，**零 ollama、零 API key**（中文較弱，堪用）
  ollama  — bge-m3，中文最強（需 ollama + `ollama pull bge-m3`）
  openai  — text-embedding-3-small，中文佳（需 OPENAI_API_KEY，微成本）

⚠ 換後端 = 既有向量作廢，必須先刪該專案的庫再重跑（Chroma 會擋混用）。

== 按專案分艙 ==
此 plugin 全域安裝、對所有專案的 SessionEnd 觸發，但**每個專案各自一個向量庫**，
互不汙染。專案身分取自 hook 注入的 CLAUDE_PROJECT_DIR（查詢時 fallback 到 cwd），
slug 化後當子資料夾名（同 Claude Code 存 projects 的命名法）。

庫位置：~/.claude/session-memory/<專案-slug>/   （env LIFEWIKI_DB_ROOT 可改根目錄）
"""
import os
from pathlib import Path

COLLECTION = "sessions"


def _project_key():
    """當前專案根目錄：hook 走 CLAUDE_PROJECT_DIR，查詢走 cwd（Claude 在專案根跑 Bash）。"""
    base = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    return Path(base).resolve()


def _slug(p):
    r"""C:\Users\u\proj → C--Users-u-proj（同 Claude Code projects 命名法，人讀得懂、不撞）。"""
    s = str(p).replace(":", "")
    for ch in ("\\", "/"):
        s = s.replace(ch, "-")
    return s.strip("-") or "default"


_DB_ROOT = Path(os.environ.get("LIFEWIKI_DB_ROOT")
                or (Path.home() / ".claude" / "session-memory"))
DB_DIR = _DB_ROOT / _slug(_project_key())        # 本專案專屬向量庫

EMBED_BACKEND = os.environ.get("LIFEWIKI_EMBED_BACKEND", "chroma").lower()
OLLAMA_EMBED_MODEL = os.environ.get("LIFEWIKI_EMBED_MODEL", "bge-m3")
OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
OPENAI_EMBED_MODEL = os.environ.get("LIFEWIKI_OPENAI_EMBED_MODEL", "text-embedding-3-small")


def _require_chromadb():
    try:
        import chromadb  # noqa: F401
    except ImportError as e:
        raise RuntimeError(
            "chromadb 未安裝 — 跑 /session-memory-setup 或 `pip install chromadb`") from e


def make_embedding_function():
    from chromadb.utils import embedding_functions as ef
    if EMBED_BACKEND == "ollama":
        return ef.OllamaEmbeddingFunction(
            url=f"{OLLAMA_URL}/api/embeddings", model_name=OLLAMA_EMBED_MODEL)
    if EMBED_BACKEND == "openai":
        return ef.OpenAIEmbeddingFunction(
            api_key=os.environ["OPENAI_API_KEY"], model_name=OPENAI_EMBED_MODEL)
    return ef.DefaultEmbeddingFunction()        # chroma 內建 MiniLM（零外部依賴）


def get_collection():
    """回傳掛好 embedding_function 的 persistent collection（add/query 自動 embed）。"""
    _require_chromadb()
    import chromadb
    DB_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(DB_DIR))
    return client.get_or_create_collection(
        COLLECTION,
        embedding_function=make_embedding_function(),
        metadata={"hnsw:space": "cosine"},
    )
