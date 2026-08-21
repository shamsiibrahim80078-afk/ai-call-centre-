"""
VERIDIQ RAG store — Qdrant local (on-disk) with in-memory fallback.
"""

from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from veridiq.rag.embeddings import cosine, embed_text  # noqa: E402

COLLECTION = "veridiq_evidence"
DIMS = 64
DATA_DIR = _ROOT / "data" / "qdrant"
CACHE_TTL_SEC = 120


class EvidenceRAG:
    def __init__(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._client = None
        self._memory: list[dict[str, Any]] = []
        self._query_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
        self._lock = __import__("threading").Lock()
        self._init_client()
        self._seed_defaults()

    def _init_client(self) -> None:
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.http import models as qm

            self._client = QdrantClient(path=str(DATA_DIR))
            names = {c.name for c in self._client.get_collections().collections}
            if COLLECTION not in names:
                self._client.create_collection(
                    collection_name=COLLECTION,
                    vectors_config=qm.VectorParams(size=DIMS, distance=qm.Distance.COSINE),
                )
            self._qm = qm
        except Exception:
            self._client = None
            self._qm = None

    def _seed_defaults(self) -> None:
        seeds = [
            {
                "text": "Central banks adjust interest rates to manage inflation and economic growth.",
                "source": "seed://macro-policy",
                "title": "Monetary policy baseline",
            },
            {
                "text": "Peer-reviewed clinical studies measure vaccine effectiveness against hospitalization.",
                "source": "seed://health-evidence",
                "title": "Clinical evidence baseline",
            },
            {
                "text": "Corporate earnings reports disclose revenue growth and completed acquisitions.",
                "source": "seed://markets",
                "title": "Corporate disclosure baseline",
            },
            {
                "text": "International treaties are signed by authorized representatives and recorded publicly.",
                "source": "seed://diplomacy",
                "title": "Treaty record baseline",
            },
        ]
        for s in seeds:
            self.upsert(s["text"], metadata={"source": s["source"], "title": s["title"]}, doc_id=s["source"])

    def upsert(
        self,
        text: str,
        *,
        metadata: Optional[dict[str, Any]] = None,
        doc_id: Optional[str] = None,
    ) -> str:
        point_id = doc_id or str(uuid.uuid4())
        vector = embed_text(text, DIMS)
        payload = {"text": text, **(metadata or {})}
        if self._client is not None:
            try:
                with self._lock:
                    self._client.upsert(
                        collection_name=COLLECTION,
                        points=[
                            self._qm.PointStruct(
                                id=abs(hash(point_id)) % (10**12),
                                vector=vector,
                                payload={**payload, "doc_id": point_id},
                            )
                        ],
                    )
                return point_id
            except Exception:
                pass
        # memory fallback / mirror
        with self._lock:
            self._memory = [m for m in self._memory if m.get("doc_id") != point_id]
            self._memory.append({"doc_id": point_id, "vector": vector, "payload": payload})
        return point_id

    def query(self, text: str, top_k: int = 5) -> list[dict[str, Any]]:
        key = f"{text.strip().lower()}::{top_k}"
        cached = self._query_cache.get(key)
        now = time.time()
        if cached and now - cached[0] < CACHE_TTL_SEC:
            return cached[1]

        vector = embed_text(text, DIMS)
        hits: list[dict[str, Any]] = []

        if self._client is not None:
            try:
                if hasattr(self._client, "query_points"):
                    response = self._client.query_points(
                        collection_name=COLLECTION,
                        query=vector,
                        limit=top_k,
                    )
                    results = response.points
                else:
                    results = self._client.search(
                        collection_name=COLLECTION,
                        query_vector=vector,
                        limit=top_k,
                    )
                for r in results:
                    payload = dict(r.payload or {})
                    hits.append(
                        {
                            "score": float(getattr(r, "score", 0) or 0),
                            "text": payload.get("text"),
                            "source": payload.get("source"),
                            "title": payload.get("title"),
                            "doc_id": payload.get("doc_id"),
                        }
                    )
            except Exception:
                hits = []

        if not hits:
            scored = []
            for item in self._memory:
                scored.append(
                    (
                        cosine(vector, item["vector"]),
                        item,
                    )
                )
            scored.sort(key=lambda x: x[0], reverse=True)
            for score, item in scored[:top_k]:
                payload = item["payload"]
                hits.append(
                    {
                        "score": round(float(score), 4),
                        "text": payload.get("text"),
                        "source": payload.get("source"),
                        "title": payload.get("title"),
                        "doc_id": item.get("doc_id"),
                    }
                )

        self._query_cache[key] = (now, hits)
        return hits

    def ingest_evidence_items(self, items: list[dict[str, Any]]) -> int:
        count = 0
        for item in items:
            text = str(item.get("snippet") or item.get("text") or item.get("claim") or "").strip()
            if not text:
                continue
            self.upsert(
                text,
                metadata={
                    "source": item.get("url") or item.get("source") or "evidence",
                    "title": item.get("title") or item.get("claim") or "evidence",
                },
            )
            count += 1
        return count

    def status(self) -> dict[str, Any]:
        try:
            with self._lock:
                backend = "qdrant" if self._client is not None else "memory"
                mem = len(self._memory)
                cache = len(self._query_cache)
            return {
                "backend": backend,
                "collection": COLLECTION,
                "dims": DIMS,
                "memory_docs": mem,
                "cache_entries": cache,
                "data_dir": str(DATA_DIR),
            }
        except Exception as exc:
            return {"backend": "error", "error": str(exc), "collection": COLLECTION}


_global_rag: Optional[EvidenceRAG] = None


def get_rag() -> EvidenceRAG:
    global _global_rag
    if _global_rag is None:
        _global_rag = EvidenceRAG()
    return _global_rag
