"""Run-scoped evidence RAG: chunk pages, embed (cached, budgeted), hybrid retrieve.
No vector service: SQLite passage table + pure-python cosine. Embeddings upgrade
retrieval; lexical overlap keeps it working when embeddings are unavailable."""
from __future__ import annotations

import math
import os
import re
import sqlite3

from connectors import http
from connectors.keys import ROOT, keys
from data import cache

CHUNK_CHARS = 500
EMBED_BUDGET = int(os.environ.get("REAVER_EMBED_BUDGET", "30"))
VEC_TABLE = "passages"

_spent = 0


def chunk(text: str, size: int = CHUNK_CHARS) -> list[str]:
    """Sentence-aware split; oversized sentences hard-cut. Order = document order."""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    chunks, current = [], ""
    for sentence in sentences:
        while len(sentence) > size:
            chunks.append(sentence[:size])
            sentence = sentence[size:]
        candidate = (current + " " + sentence).strip()
        if len(candidate) <= size:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = sentence
    if current:
        chunks.append(current)
    return chunks


def _passage_db() -> sqlite3.Connection:
    con = sqlite3.connect(os.path.join(ROOT, "data", "reaver.db"))
    con.execute("CREATE TABLE IF NOT EXISTS %s (k TEXT, idx INTEGER, text TEXT, vec TEXT,"
                " PRIMARY KEY (k, idx))" % VEC_TABLE)
    return con


def store_passages(owner: str, texts: list[str]) -> list[dict]:
    """Persist chunks; embed up to budget (cached by text hash), rest lexical-only."""
    global _spent
    import json
    con = _passage_db()
    try:
        out = []
        for index, text in enumerate(texts):
            vec = cache.get(cache.make_key("vec", text))
            if vec is None and _spent < EMBED_BUDGET:
                vec = _embed(text)
                _spent += 1
                if vec is not None:
                    cache.put(cache.make_key("vec", text), vec, 30 * 24 * 3600)
            pid = "%s#%d" % (owner, index)
            con.execute("REPLACE INTO %s VALUES (?, ?, ?, ?)" % VEC_TABLE,
                        (owner, index, text, json.dumps(vec) if vec else None))
            out.append({"id": pid, "text": text, "vector": vec})
        con.commit()
        return out
    finally:
        con.close()


def load_passages(owner: str) -> list[dict]:
    import json
    con = _passage_db()
    try:
        rows = con.execute("SELECT idx, text, vec FROM %s WHERE k = ? ORDER BY idx" % VEC_TABLE,
                           (owner,)).fetchall()
        return [{"id": "%s#%d" % (owner, i), "text": t,
                 "vector": json.loads(v) if v else None} for i, t, v in rows]
    finally:
        con.close()


def _embed(text: str) -> list[float] | None:
    """Gemini free embedding. None on any failure — caller falls back to lexical."""
    available = keys("GEMINI_API_KEY")
    if not available:
        return None
    res = http.call("https://generativelanguage.googleapis.com/v1beta/models/"
                    "text-embedding-004:embedContent?key=" + available[0],
                    method="POST", payload={"content": {"parts": [{"text": text[:2000]}]}})
    if res["http"] != 200:
        return None
    values = ((http.json_body(res) or {}).get("embedding") or {}).get("values")
    return [float(v) for v in values] if values else None


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def _tokens(text: str) -> set[str]:
    return {w for w in re.sub(r"[^a-z0-9 ]", "", text.lower()).split() if len(w) > 3}


def retrieve(criterion: str, passages: list[dict], top: int = 2) -> list[dict]:
    """Hybrid rank: 0.7 cosine + 0.3 overlap when vectors exist, else pure overlap."""
    global _spent
    wants = _tokens(criterion)
    if not wants:
        return []
    query_vec = cache.get(cache.make_key("vec", criterion))
    if query_vec is None and _spent < EMBED_BUDGET and any(p.get("vector") for p in passages):
        query_vec = _embed(criterion)
        _spent += 1
        if query_vec is not None:
            cache.put(cache.make_key("vec", criterion), query_vec, 30 * 24 * 3600)
    scored = []
    for passage in passages:
        overlap = len(wants & _tokens(passage["text"])) / len(wants)
        if overlap == 0:
            continue
        score = overlap
        if query_vec and passage.get("vector"):
            try:
                score = 0.7 * cosine(query_vec, passage["vector"]) + 0.3 * overlap
            except (ValueError, TypeError, ZeroDivisionError):
                pass
        scored.append((score, passage))
    scored.sort(key=lambda s: -s[0])
    return [p for _, p in scored[:top]]
