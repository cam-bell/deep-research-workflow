from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from collections import deque
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urldefrag, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import httpx
import tiktoken
from bs4 import BeautifulSoup, Tag
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, model_validator
from supabase import Client, create_client

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rag.chunker import chunk_document
from rag.embedder import embed_texts

logger = logging.getLogger(__name__)
load_dotenv()

_USER_AGENT = "deep-research-workflow-ingest/1.0"
_MIN_CONTENT_LENGTH = 200
_REQUEST_DELAY_SECONDS = 1.0
_ENCODING = tiktoken.get_encoding("cl100k_base")
_BLOCKED_TAGS = {
    "nav",
    "footer",
    "aside",
    "script",
    "style",
    "noscript",
    "form",
    "button",
    "input",
    "select",
    "textarea",
    "svg",
}
_CONTENT_TAGS = {
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "p",
    "li",
    "pre",
    "code",
    "blockquote",
    "table",
}
_CONTAINER_TAGS = ("main", "article", "section", "div")


class SourceConfig(BaseModel):
    key: str
    source_name: str
    max_pages: int
    base_url: str | None = None
    start_paths: list[str] = Field(default_factory=list)
    urls: list[str] = Field(default_factory=list)

    model_config = ConfigDict(frozen=True)

    @model_validator(mode="after")
    def validate_seed_configuration(self) -> "SourceConfig":
        if not self.base_url and not self.urls:
            raise ValueError("Source config must define either base_url or urls")
        if self.base_url and not self.start_paths and not self.urls:
            raise ValueError("Source config with base_url must define start_paths")
        return self

    @property
    def seed_urls(self) -> list[str]:
        if self.urls:
            return self.urls
        assert self.base_url is not None
        return [urljoin(self.base_url, path) for path in self.start_paths]

    @property
    def allowed_hosts(self) -> set[str]:
        hosts = set()
        for url in self.seed_urls:
            host = urlparse(url).netloc
            if host:
                hosts.add(host)
        if self.base_url:
            hosts.add(urlparse(self.base_url).netloc)
        return hosts

    @property
    def allowed_path_prefixes(self) -> tuple[str, ...]:
        if self.urls:
            return tuple()
        return tuple(self.start_paths)


class FetchedPage(BaseModel):
    url: str
    html: str


class ParsedDocument(BaseModel):
    source_name: str
    source_url: str
    section_title: str
    content: str
    discovered_links: list[str]


class CorpusChunkRow(BaseModel):
    source_name: str
    source_url: str
    section_title: str
    content: str
    embedding: list[float]
    chunk_index: int


class IngestionStats(BaseModel):
    source_name: str
    pages_fetched: int = 0
    pages_skipped: int = 0
    chunks_created: int = 0
    chunks_inserted: int = 0
    token_estimate: int = 0


class RobotsPolicyCache:
    def __init__(self) -> None:
        self._policies: dict[str, RobotFileParser] = {}

    async def can_fetch(self, client: httpx.AsyncClient, url: str) -> bool:
        parsed = urlparse(url)
        host = parsed.netloc
        if host in self._policies:
            return self._policies[host].can_fetch(_USER_AGENT, url)

        robots_url = urlunparse((parsed.scheme, parsed.netloc, "/robots.txt", "", "", ""))
        parser = RobotFileParser()
        try:
            response = await client.get(robots_url, follow_redirects=True)
            if response.status_code == 200:
                parser.parse(response.text.splitlines())
            else:
                parser.parse(["User-agent: *", "Allow: /"])
        except httpx.HTTPError:
            parser.parse(["User-agent: *", "Allow: /"])

        self._policies[host] = parser
        return parser.can_fetch(_USER_AGENT, url)


SOURCES: dict[str, SourceConfig] = {
    "gitlab-handbook": SourceConfig(
        key="gitlab-handbook",
        base_url="https://handbook.gitlab.com",
        start_paths=["/engineering/", "/product/", "/hiring/", "/security/"],
        source_name="GitLab Handbook",
        max_pages=500,
    ),
    "stripe-docs": SourceConfig(
        key="stripe-docs",
        base_url="https://docs.stripe.com",
        start_paths=["/api", "/payments", "/connect", "/billing"],
        source_name="Stripe API Documentation",
        max_pages=200,
    ),
    "anthropic-docs": SourceConfig(
        key="anthropic-docs",
        base_url="https://platform.claude.com",
        start_paths=["docs/en/intro", "docs/en/api", "docs/en/build-with-claude/overview", "docs/en/about-claude/models/overview"],
        source_name="Anthropic API Documentation",
        max_pages=100,
    ),
    "openai-docs": SourceConfig(
        key="openai-docs",
        base_url="https://developers.openai.com",
        start_paths=["/api/docs/", "/api/reference/overview/", "/api/docs/models/"],
        source_name="OpenAI API Documentation",
        max_pages=100,
    ),
    "aws-waf": SourceConfig(
        key="aws-waf",
        base_url="https://docs.aws.amazon.com",
        start_paths=["/wellarchitected/latest/framework/"],
        source_name="AWS Well-Architected Framework",
        max_pages=150,
    ),
    "engineering-rfcs": SourceConfig(
        key="engineering-rfcs",
        urls=[
            "https://blog.cloudflare.com/tag/engineering/",
            "https://www.uber.com/blog/engineering/",
            "https://netflixtechblog.com/",
            "https://github.blog/engineering/",
        ],
        source_name="Engineering RFCs and ADRs",
        max_pages=50,
    ),
}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ingest documentation into Supabase.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--source", choices=sorted(SOURCES.keys()))
    mode.add_argument("--all", action="store_true")
    parser.add_argument("--limit", type=int, default=None, help="Maximum pages per source.")
    return parser


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _get_supabase_client() -> Client:
    return create_client(
        _require_env("SUPABASE_URL"),
        _require_env("SUPABASE_SERVICE_KEY"),
    )


def _normalize_url(url: str) -> str:
    clean_url, _ = urldefrag(url)
    parsed = urlparse(clean_url)
    normalized_path = parsed.path or "/"
    if normalized_path != "/":
        normalized_path = normalized_path.rstrip("/") or "/"
    return urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            normalized_path,
            "",
            "",
            "",
        )
    )


def _is_allowed_url(url: str, config: SourceConfig) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    if parsed.netloc not in config.allowed_hosts:
        return False
    if config.allowed_path_prefixes and not any(
        parsed.path.startswith(prefix) for prefix in config.allowed_path_prefixes
    ):
        return False
    return True


def _strip_noise(container: Tag) -> None:
    for tag in list(container.find_all(_BLOCKED_TAGS)):
        tag.decompose()

    noisy_selectors = (
        lambda element: any(
            token in " ".join(element.get("class", [])).lower()
            for token in ("nav", "footer", "sidebar", "cookie", "advert", "promo")
        ),
        lambda element: any(
            token in (element.get("id") or "").lower()
            for token in ("nav", "footer", "sidebar", "cookie", "advert", "promo")
        ),
        lambda element: element.get("role") in {"navigation", "banner", "complementary"},
    )

    for element in list(container.find_all(True)):
        if any(check(element) for check in noisy_selectors):
            element.decompose()


def _select_content_container(soup: BeautifulSoup) -> Tag | None:
    for selector in ("main", "article"):
        container = soup.find(selector)
        if isinstance(container, Tag):
            return container

    best_container: Tag | None = None
    best_length = 0
    for candidate in soup.find_all(_CONTAINER_TAGS):
        text = candidate.get_text(" ", strip=True)
        length = len(text)
        if length > best_length:
            best_length = length
            best_container = candidate

    body = soup.body
    return best_container if isinstance(best_container, Tag) else body


def _candidate_containers(soup: BeautifulSoup) -> list[Tag]:
    candidates: list[Tag] = []
    seen: set[int] = set()

    for selector in ("main", "article"):
        container = soup.find(selector)
        if isinstance(container, Tag) and id(container) not in seen:
            candidates.append(container)
            seen.add(id(container))

    best_container = _select_content_container(soup)
    if isinstance(best_container, Tag) and id(best_container) not in seen:
        candidates.append(best_container)
        seen.add(id(best_container))

    if isinstance(soup.body, Tag) and id(soup.body) not in seen:
        candidates.append(soup.body)

    return candidates


def _render_content(container: Tag) -> tuple[str, str]:
    lines: list[str] = []
    first_heading = ""

    for node in container.find_all(_CONTENT_TAGS):
        text = node.get_text("\n" if node.name == "pre" else " ", strip=True)
        if not text:
            continue
        if node.name and node.name.startswith("h") and node.name[1:].isdigit():
            heading_level = int(node.name[1])
            rendered = f"{'#' * heading_level} {text}"
            if not first_heading:
                first_heading = text
        elif node.name == "li":
            rendered = f"- {text}"
        elif node.name == "pre":
            rendered = f"```\n{text}\n```"
        elif node.name == "blockquote":
            rendered = "\n".join(f"> {line}" for line in text.splitlines() if line.strip())
        else:
            rendered = text

        if lines and lines[-1] == rendered:
            continue
        lines.append(rendered)

    return "\n\n".join(lines).strip(), first_heading


def _extract_links(container: Tag, current_url: str, config: SourceConfig) -> list[str]:
    discovered_links: list[str] = []
    seen: set[str] = set()

    for link in container.find_all("a", href=True):
        normalized = _normalize_url(urljoin(current_url, link["href"]))
        if normalized in seen or not _is_allowed_url(normalized, config):
            continue
        seen.add(normalized)
        discovered_links.append(normalized)

    return discovered_links


def _parse_document(page: FetchedPage, config: SourceConfig) -> ParsedDocument | None:
    soup = BeautifulSoup(page.html, "html.parser")
    page_title = ""
    if soup.title and soup.title.string:
        page_title = soup.title.string.strip()

    best_document: ParsedDocument | None = None
    best_length = 0

    for candidate in _candidate_containers(soup):
        candidate_soup = BeautifulSoup(str(candidate), "html.parser")
        container = candidate_soup.find()
        if not isinstance(container, Tag):
            continue

        _strip_noise(container)
        content, first_heading = _render_content(container)
        if len(content) < _MIN_CONTENT_LENGTH:
            continue

        section_title = first_heading or page_title or config.source_name
        document = ParsedDocument(
            source_name=config.source_name,
            source_url=page.url,
            section_title=section_title,
            content=content,
            discovered_links=_extract_links(container, page.url, config),
        )
        if len(document.content) > best_length:
            best_document = document
            best_length = len(document.content)

    return best_document


async def _fetch_page(
    client: httpx.AsyncClient,
    url: str,
    robots_cache: RobotsPolicyCache,
) -> FetchedPage | None:
    allowed = await robots_cache.can_fetch(client, url)
    if not allowed:
        logger.info("Skipping robots-blocked url=%s", url)
        return None

    try:
        response = await client.get(url, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPError:
        logger.exception("Failed to fetch url=%s", url)
        return None
    finally:
        await asyncio.sleep(_REQUEST_DELAY_SECONDS)

    content_type = response.headers.get("content-type", "")
    if "text/html" not in content_type:
        logger.info("Skipping non-HTML url=%s content_type=%s", url, content_type)
        return None

    return FetchedPage(url=_normalize_url(str(response.url)), html=response.text)


async def _select_existing_chunk_indices(client: Client, source_url: str) -> set[int]:
    def _run() -> Any:
        return (
            client.table("corpus_chunks")
            .select("chunk_index")
            .eq("source_url", source_url)
            .execute()
        )

    response = await asyncio.to_thread(_run)
    return {
        int(item["chunk_index"])
        for item in (response.data or [])
        if item.get("chunk_index") is not None
    }


async def _insert_chunk_rows(client: Client, rows: list[CorpusChunkRow]) -> int:
    if not rows:
        return 0

    payload = [row.model_dump() for row in rows]

    def _run() -> Any:
        return client.table("corpus_chunks").insert(payload).execute()

    await asyncio.to_thread(_run)
    return len(rows)


async def _ingest_document(
    supabase_client: Client,
    document: ParsedDocument,
    stats: IngestionStats,
) -> int:
    chunks = chunk_document(
        content=document.content,
        source_name=document.source_name,
        source_url=document.source_url,
        section_title=document.section_title,
    )
    stats.chunks_created += len(chunks)
    stats.token_estimate += sum(len(_ENCODING.encode(chunk.content)) for chunk in chunks)

    existing_indices = await _select_existing_chunk_indices(
        supabase_client,
        document.source_url,
    )
    new_chunks = [chunk for chunk in chunks if chunk.chunk_index not in existing_indices]
    if not new_chunks:
        return 0

    embeddings = await embed_texts([chunk.content for chunk in new_chunks])
    rows = [
        CorpusChunkRow(
            source_name=chunk.source_name,
            source_url=chunk.source_url,
            section_title=chunk.section_title,
            content=chunk.content,
            embedding=embedding,
            chunk_index=chunk.chunk_index,
        )
        for chunk, embedding in zip(new_chunks, embeddings, strict=True)
    ]
    inserted = await _insert_chunk_rows(supabase_client, rows)
    stats.chunks_inserted += inserted
    return inserted


async def ingest_source(
    config: SourceConfig,
    limit: int | None = None,
) -> IngestionStats:
    page_limit = min(config.max_pages, limit) if limit is not None else config.max_pages
    stats = IngestionStats(source_name=config.source_name)
    queue: deque[str] = deque(_normalize_url(url) for url in config.seed_urls)
    seen: set[str] = set(queue)
    robots_cache = RobotsPolicyCache()
    supabase_client = _get_supabase_client()

    headers = {"User-Agent": _USER_AGENT}
    timeout = httpx.Timeout(20.0, connect=10.0)
    async with httpx.AsyncClient(headers=headers, timeout=timeout) as http_client:
        while queue and stats.pages_fetched < page_limit:
            url = queue.popleft()
            page = await _fetch_page(http_client, url, robots_cache)
            if page is None:
                stats.pages_skipped += 1
                continue

            document = _parse_document(page, config)
            if document is None:
                stats.pages_skipped += 1
                continue

            stats.pages_fetched += 1
            for link in document.discovered_links:
                if link in seen or not _is_allowed_url(link, config):
                    continue
                if len(seen) >= page_limit * 20:
                    continue
                seen.add(link)
                queue.append(link)

            await _ingest_document(supabase_client, document, stats)
            logger.info(
                "Progress source=%s pages_fetched=%s pages_skipped=%s chunks_created=%s chunks_inserted=%s token_estimate=%s",
                config.source_name,
                stats.pages_fetched,
                stats.pages_skipped,
                stats.chunks_created,
                stats.chunks_inserted,
                stats.token_estimate,
            )

    logger.info(
        "Completed source=%s pages_fetched=%s pages_skipped=%s chunks_created=%s chunks_inserted=%s token_estimate=%s",
        config.source_name,
        stats.pages_fetched,
        stats.pages_skipped,
        stats.chunks_created,
        stats.chunks_inserted,
        stats.token_estimate,
    )
    print(f"Ingested {stats.chunks_inserted} chunks from {config.source_name}")
    return stats


async def _run(args: argparse.Namespace) -> list[IngestionStats]:
    selected_sources = (
        [SOURCES[args.source]]
        if args.source
        else [SOURCES[key] for key in sorted(SOURCES.keys())]
    )
    results: list[IngestionStats] = []
    for source in selected_sources:
        results.append(await ingest_source(source, limit=args.limit))
    return results


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    parser = _build_parser()
    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
