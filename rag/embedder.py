from __future__ import annotations

import logging

from dotenv import load_dotenv
from openai import APIError, AsyncOpenAI

logger = logging.getLogger(__name__)

_EMBEDDING_MODEL = "text-embedding-3-small"
_EMBEDDING_DIMENSIONS = 1536
_BATCH_SIZE = 100
_client: AsyncOpenAI | None = None

load_dotenv()


class EmbeddingError(Exception):
    pass


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI()
    return _client


async def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []

    embeddings: list[list[float]] = []

    for batch_start in range(0, len(texts), _BATCH_SIZE):
        batch = texts[batch_start : batch_start + _BATCH_SIZE]
        try:
            response = await _get_client().embeddings.create(
                model=_EMBEDDING_MODEL,
                input=batch,
            )
        except APIError as exc:
            logger.exception(
                "Embedding request failed for batch starting at index %s",
                batch_start,
            )
            raise EmbeddingError("Failed to generate embeddings") from exc
        except Exception as exc:  # pragma: no cover - defensive wrapper
            logger.exception(
                "Unexpected embedding failure for batch starting at index %s",
                batch_start,
            )
            raise EmbeddingError("Failed to generate embeddings") from exc

        usage = getattr(response, "usage", None)
        prompt_tokens = getattr(usage, "prompt_tokens", None)
        total_tokens = getattr(usage, "total_tokens", None)
        logger.info(
            "Embedded batch start=%s size=%s prompt_tokens=%s total_tokens=%s",
            batch_start,
            len(batch),
            prompt_tokens,
            total_tokens,
        )

        for item in response.data:
            vector = item.embedding
            if len(vector) != _EMBEDDING_DIMENSIONS:
                raise EmbeddingError(
                    f"Unexpected embedding size {len(vector)}; expected {_EMBEDDING_DIMENSIONS}"
                )
            embeddings.append(vector)

    return embeddings


async def embed_single(text: str) -> list[float]:
    embeddings = await embed_texts([text])
    if not embeddings:
        raise EmbeddingError("Embedding response was empty")
    return embeddings[0]
