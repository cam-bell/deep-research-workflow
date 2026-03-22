from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from postgrest.exceptions import APIError
from pydantic import BaseModel
from rank_bm25 import BM25Okapi
from supabase import Client, create_client

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rag.embedder import embed_single

logger = logging.getLogger(__name__)
load_dotenv()

_RRF_K = 60
_DEFAULT_TOP_K = 5
_MIN_CANDIDATES = 20
_TOKEN_PATTERN = re.compile(r"\b\w+\b")


class CorpusChunk(BaseModel):
    id: str | None = None
    content: str
    source_name: str
    source_url: str
    section_title: str
    chunk_index: int


class RetrievedChunk(BaseModel):
    content: str
    source_name: str
    source_url: str
    section_title: str
    score: float


_supabase_client: Client | None = None
_corpus_cache: list[CorpusChunk] | None = None
_tokenized_corpus: list[list[str]] | None = None
_bm25_index: BM25Okapi | None = None
_cache_lock = asyncio.Lock()


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _get_supabase_client() -> Client:
    global _supabase_client
    if _supabase_client is None:
        _supabase_client = create_client(
            _require_env("SUPABASE_URL"),
            _require_env("SUPABASE_SERVICE_KEY"),
        )
    return _supabase_client


def _tokenize(text: str) -> list[str]:
    return _TOKEN_PATTERN.findall(text.lower())


async def _fetch_all_corpus_rows() -> list[CorpusChunk]:
    client = _get_supabase_client()
    page_size = 1000
    offset = 0
    rows: list[CorpusChunk] = []

    while True:
        def _run() -> Any:
            return (
                client.table("corpus_chunks")
                .select("id,content,source_name,source_url,section_title,chunk_index")
                .range(offset, offset + page_size - 1)
                .execute()
            )

        response = await asyncio.to_thread(_run)
        page_rows = response.data or []
        if not page_rows:
            break

        rows.extend(
            CorpusChunk(
                id=str(item["id"]) if item.get("id") is not None else None,
                content=item["content"],
                source_name=item["source_name"],
                source_url=item["source_url"],
                section_title=item.get("section_title") or "",
                chunk_index=int(item.get("chunk_index") or 0),
            )
            for item in page_rows
        )
        if len(page_rows) < page_size:
            break
        offset += page_size

    return rows


async def _ensure_corpus_cache() -> list[CorpusChunk]:
    global _corpus_cache, _tokenized_corpus, _bm25_index

    if (
        _corpus_cache is not None
        and _tokenized_corpus is not None
        and _bm25_index is not None
    ):
        return _corpus_cache

    async with _cache_lock:
        if (
            _corpus_cache is not None
            and _tokenized_corpus is not None
            and _bm25_index is not None
        ):
            return _corpus_cache

        _corpus_cache = await _fetch_all_corpus_rows()
        _tokenized_corpus = [_tokenize(chunk.content) for chunk in _corpus_cache]
        _bm25_index = BM25Okapi(_tokenized_corpus) if _tokenized_corpus else None
        logger.info("Loaded corpus cache rows=%s", len(_corpus_cache))
        return _corpus_cache


def _candidate_count(top_k: int) -> int:
    return max(top_k * 5, _MIN_CANDIDATES)


def _chunk_key(chunk: CorpusChunk) -> str:
    return f"{chunk.source_url}::{chunk.chunk_index}"


def _get_bm25_candidates(query: str, limit: int) -> list[CorpusChunk]:
    if _corpus_cache is None or _tokenized_corpus is None or _bm25_index is None:
        return []

    query_tokens = _tokenize(query)
    if not query_tokens:
        return []

    scores = _bm25_index.get_scores(query_tokens)
    ranked_indices = sorted(
        range(len(scores)),
        key=lambda index: scores[index],
        reverse=True,
    )
    return [
        _corpus_cache[index]
        for index in ranked_indices
        if scores[index] > 0
    ][:limit]


async def _vector_search(query: str, limit: int) -> list[CorpusChunk]:
    query_embedding = await embed_single(query)
    client = _get_supabase_client()

    def _run() -> Any:
        return (
            client.rpc(
                "match_chunks",
                {
                    "query_embedding": query_embedding,
                    "match_count": limit,
                },
            ).execute()
        )

    try:
        response = await asyncio.to_thread(_run)
    except APIError:
        logger.exception("RPC match_chunks failed")
        raise

    return [
        CorpusChunk(
            id=str(item["id"]) if item.get("id") is not None else None,
            content=item["content"],
            source_name=item["source_name"],
            source_url=item["source_url"],
            section_title=item.get("section_title") or "",
            chunk_index=_lookup_chunk_index(item),
        )
        for item in (response.data or [])
    ]


def _lookup_chunk_index(item: dict[str, Any]) -> int:
    if _corpus_cache is None:
        return 0
    item_id = str(item["id"]) if item.get("id") is not None else None
    if item_id is None:
        return 0
    for chunk in _corpus_cache:
        if chunk.id == item_id:
            return chunk.chunk_index
    return 0


def _rrf_fuse(
    bm25_chunks: list[CorpusChunk],
    vector_chunks: list[CorpusChunk],
    top_k: int,
) -> list[RetrievedChunk]:
    bm25_ranks = {_chunk_key(chunk): rank for rank, chunk in enumerate(bm25_chunks, start=1)}
    vector_ranks = {_chunk_key(chunk): rank for rank, chunk in enumerate(vector_chunks, start=1)}
    merged: dict[str, RetrievedChunk] = {}

    for chunk in bm25_chunks + vector_chunks:
        key = _chunk_key(chunk)
        bm25_rank = bm25_ranks.get(key)
        vector_rank = vector_ranks.get(key)
        score = 0.0
        if bm25_rank is not None:
            score += 1.0 / (_RRF_K + bm25_rank)
        if vector_rank is not None:
            score += 1.0 / (_RRF_K + vector_rank)

        merged[key] = RetrievedChunk(
            content=chunk.content,
            source_name=chunk.source_name,
            source_url=chunk.source_url,
            section_title=chunk.section_title,
            score=score,
        )

    return sorted(merged.values(), key=lambda chunk: chunk.score, reverse=True)[:top_k]


async def retrieve(
    query: str,
    top_k: int = _DEFAULT_TOP_K,
) -> list[RetrievedChunk]:
    corpus = await _ensure_corpus_cache()
    if not corpus:
        return []

    limit = _candidate_count(top_k)
    bm25_chunks = _get_bm25_candidates(query, limit)
    vector_chunks = await _vector_search(query, limit)
    return _rrf_fuse(bm25_chunks, vector_chunks, top_k)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Retrieve ranked chunks from the corpus.")
    parser.add_argument("--query", required=True)
    parser.add_argument("--top-k", type=int, default=_DEFAULT_TOP_K)
    return parser


async def _run_cli(query: str, top_k: int) -> int:
    results = await retrieve(query, top_k=top_k)
    if not results:
        print("No results found.")
        return 0

    for index, chunk in enumerate(results, start=1):
        excerpt = chunk.content.replace("\n", " ").strip()
        if len(excerpt) > 240:
            excerpt = excerpt[:237] + "..."
        print(f"{index}. score={chunk.score:.6f}")
        print(f"   source={chunk.source_name}")
        print(f"   section={chunk.section_title}")
        print(f"   url={chunk.source_url}")
        print(f"   excerpt={excerpt}")
    return 0


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    parser = _build_parser()
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run_cli(args.query, args.top_k)))


if __name__ == "__main__":
    main()
