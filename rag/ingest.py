from __future__ import annotations

import argparse
import asyncio
import logging
import os
import random
import re
import ssl
import sys
from collections import deque
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urldefrag, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import httpx
import tiktoken
from postgrest.exceptions import APIError
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
_MIN_CONTENT_WORDS = 200
_REQUEST_DELAY_SECONDS = 1.0
_MAX_FETCH_ATTEMPTS = 3
_MAX_INSERT_ATTEMPTS = 3
_MAX_INSERT_BATCH_SIZE = 25
_INITIAL_BACKOFF_SECONDS = 0.5
_RETRYABLE_API_STATUS_CODES = {408, 429, 500, 502, 503, 504}
_ENCODING = tiktoken.get_encoding("cl100k_base")
_BLOCKED_TAGS = {
    "header",
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
_WORD_PATTERN = re.compile(r"\b\w+\b")
_DEFAULT_BLOCKED_PATH_SUBSTRINGS = (
    "/pricing",
    "/login",
    "/logout",
    "/signin",
    "/signup",
    "/404",
    "/not-found",
    "/search",
    "/feed",
    "/rss",
    "/newsletter",
    "/account",
)
_NOISE_SECTION_TERMS = ("cookie", "privacy", "consent", "preferences")
_supabase_client: Client | None = None


class SourceConfig(BaseModel):
    key: str
    source_name: str
    max_pages: int
    base_url: str | None = None
    start_paths: list[str] = Field(default_factory=list)
    urls: list[str] = Field(default_factory=list)
    redirect_allowed_hosts: list[str] = Field(default_factory=list)
    redirect_passthrough_hosts: list[str] = Field(default_factory=list)
    blocked_path_substrings: list[str] = Field(default_factory=list)
    allowed_path_prefixes: list[str] = Field(default_factory=list)
    extra_headers: dict[str, str] = Field(default_factory=dict)
    tls_fallback_strategy: str | None = None
    known_failure_label: str | None = None

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
        hosts.update(host for host in self.redirect_allowed_hosts if host)
        return hosts


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
    final_status: str = "completed"
    status_detail: str | None = None


class SourceFetchBlocked(Exception):
    def __init__(self, status: str, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


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
        start_paths=["/handbook/engineering/", "/handbook/product/", "/handbook/hiring/", "/handbook/security/", "/handbook/business-technology/", "/handbook/eta/"],
        source_name="GitLab Handbook",
        max_pages=500,
        blocked_path_substrings=["/blog/"],
    ),
    "stripe-docs": SourceConfig(
        key="stripe-docs",
        base_url="https://docs.stripe.com",
        start_paths=["/api", "/payments", "/connect", "/billing", "/webhooks", "/error-handling"],
        source_name="Stripe API Documentation",
        max_pages=200,
        blocked_path_substrings=["/blog/", "/changelog/"],
    ),
    "anthropic-docs": SourceConfig(
        key="anthropic-docs",
        base_url="https://platform.claude.com",
        start_paths=["docs/en/home", "docs/en/intro", "docs/en/api/overview", "docs/en/build-with-claude/overview", "docs/en/about-claude/models/overview"],
        source_name="Anthropic API Documentation",
        max_pages=100,
        redirect_allowed_hosts=["docs.anthropic.com"],
        blocked_path_substrings=["/changelog/"],
    ),
    "openai-docs": SourceConfig(
        key="openai-docs",
        base_url="https://developers.openai.com",
        start_paths=["/api/docs", "/api/reference/overview/", "/api/docs/models/"],
        source_name="OpenAI API Documentation",
        max_pages=100,
        blocked_path_substrings=["/blog/", "/changelog/"],
    ),
    "aws-waf": SourceConfig(
        key="aws-waf",
        base_url="https://docs.aws.amazon.com",
        start_paths=["/wellarchitected/latest/framework/",
            "/wellarchitected/latest/framework/welcome.html",
            "/wellarchitected/latest/framework/operational-excellence.html",
            "/wellarchitected/latest/framework/security.html",
            "/wellarchitected/latest/framework/reliability.html",
            "/wellarchitected/latest/framework/performance-efficiency.html",
            "/wellarchitected/latest/framework/cost-optimization.html",
            "/wellarchitected/latest/framework/sustainability.html"],
        source_name="AWS Well-Architected Framework",
        max_pages=150,
        blocked_path_substrings=["/blogs/"],
    ),
    "cloudflare-rfcs": SourceConfig(
        key="cloudflare-rfcs",
        urls=[
            "https://blog.cloudflare.com/tag/engineering/",
        ],
        source_name="Engineering RFCs and ADRs (Cloudflare)",
        max_pages=25,
        blocked_path_substrings=["/pricing", "/login", "/account", "/tag/", "/author/", "/cdn-cgi/"],
    ),
    "uber-rfcs": SourceConfig(
        key="uber-rfcs",
        urls=[
            "https://www.uber.com/blog/engineering/",
        ],
        source_name="Engineering RFCs and ADRs (Uber)",
        max_pages=15,
        blocked_path_substrings=["/pricing", "/login", "/account", "/author/", "/tag/"],
        allowed_path_prefixes=["/blog/"],
        extra_headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
    ),
    "netflix-rfcs": SourceConfig(
        key="netflix-rfcs",
        urls=[
            "https://netflixtechblog.com/scaling-global-storytelling-modernizing-localization-analytics-at-netflix-816f47290641",
            "https://netflixtechblog.com/optimizing-recommendation-systems-with-jdks-vector-api-30d2830401ec",
            "https://netflixtechblog.com/mount-mayhem-at-netflix-scaling-containers-on-modern-cpus-f3b09b68beac",
            "https://netflixtechblog.com/mediafm-the-multimodal-ai-foundation-for-media-understanding-at-netflix-e8c28df82e2d",
            "https://netflixtechblog.com/scaling-llm-post-training-at-netflix-0046f8790194",
            "https://netflixtechblog.com/automating-rds-postgres-to-aurora-postgres-migration-261ca045447f",
            "https://netflixtechblog.com/the-ai-evolution-of-graph-search-at-netflix-d416ec5b1151",
            "https://netflixtechblog.com/how-temporal-powers-reliable-cloud-operations-at-netflix-73c69ccb5953",
            "https://netflixtechblog.com/netflix-live-origin-41f1b0ad5371",
            "https://netflixtechblog.com/av1-now-powering-30-of-netflix-streaming-02f592242d80",
            "https://netflixtechblog.com/supercharging-the-ml-and-ai-development-experience-at-netflix-b2d5b95c63eb",
        ],
        source_name="Engineering RFCs and ADRs (Netflix)",
        max_pages=15,
        redirect_passthrough_hosts=["medium.com"],
        blocked_path_substrings=["/pricing", "/login", "/account", "/tag/", "/tagged/", "/author/", "/followers"],
        tls_fallback_strategy="system_trust_store",
        known_failure_label="environment_blocked_tls",
    ),
    "github-rfcs": SourceConfig(
        key="github-rfcs",
        urls=[
            "https://github.blog/engineering/",
        ],
        source_name="Engineering RFCs and ADRs (GitHub)",
        max_pages=50,
        blocked_path_substrings=["/pricing", "/login", "/account", "/tag/", "/author/", "/categories/"],
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
    global _supabase_client
    if _supabase_client is None:
        _supabase_client = create_client(
            _require_env("SUPABASE_URL"),
            _require_env("SUPABASE_SERVICE_KEY"),
        )
    return _supabase_client


def _reset_supabase_client() -> Client:
    global _supabase_client
    _supabase_client = None
    return _get_supabase_client()


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
    normalized = _normalize_url(url)
    if normalized in {_normalize_url(seed_url) for seed_url in config.seed_urls}:
        return True

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    if parsed.netloc not in config.allowed_hosts:
        return False
    if config.allowed_path_prefixes and not any(
        parsed.path.startswith(prefix) for prefix in config.allowed_path_prefixes
    ):
        return False
    if _is_blocked_path(parsed.path, config):
        return False
    return True


def _is_blocked_path(path: str, config: SourceConfig) -> bool:
    path_lower = path.lower()
    blocked_terms = _DEFAULT_BLOCKED_PATH_SUBSTRINGS + tuple(config.blocked_path_substrings)
    return any(term in path_lower for term in blocked_terms)


def _build_client_headers(config: SourceConfig) -> dict[str, str]:
    headers = {"User-Agent": _USER_AGENT}
    headers.update(config.extra_headers)
    return headers


def _class_tokens(element: Tag) -> list[str]:
    attrs = element.attrs if isinstance(getattr(element, "attrs", None), dict) else {}
    raw_classes = attrs.get("class", [])
    if isinstance(raw_classes, str):
        return raw_classes.split()
    if isinstance(raw_classes, list):
        return [str(token) for token in raw_classes]
    return []


def _id_value(element: Tag) -> str:
    attrs = element.attrs if isinstance(getattr(element, "attrs", None), dict) else {}
    raw_id = attrs.get("id")
    return str(raw_id) if raw_id is not None else ""


def _attr_value(element: Tag, name: str) -> str:
    attrs = element.attrs if isinstance(getattr(element, "attrs", None), dict) else {}
    value = attrs.get(name)
    return str(value) if value is not None else ""


def _strip_noise(container: Tag) -> None:
    for tag in list(container.find_all(_BLOCKED_TAGS)):
        tag.decompose()

    noisy_selectors = (
        lambda element: any(
            token in " ".join(_class_tokens(element)).lower()
            for token in ("nav", "footer", "sidebar", "cookie", "advert", "promo")
        ),
        lambda element: any(
            token in _id_value(element).lower()
            for token in ("nav", "footer", "sidebar", "cookie", "advert", "promo")
        ),
        lambda element: _attr_value(element, "role") in {"navigation", "banner", "complementary"},
    )

    for element in list(container.find_all(True)):
        if any(check(element) for check in noisy_selectors):
            element.decompose()


def _select_content_container(soup: BeautifulSoup) -> Tag | None:
    for selector in ("main", "article", '[role="main"]', ".content", ".docs-content", ".markdown-body"):
        container = soup.select_one(selector)
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

    for selector in ("main", "article", '[role="main"]', ".content", ".docs-content", ".markdown-body"):
        container = soup.select_one(selector)
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
            if not first_heading and not _is_noise_section_text(text):
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


def _is_noise_section_text(text: str) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in _NOISE_SECTION_TERMS)


def _word_count(text: str) -> int:
    return len(_WORD_PATTERN.findall(text))


def _is_listing_like_page(content: str, discovered_links: list[str]) -> bool:
    return len(discovered_links) >= 12 and _word_count(content) < 350


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
        if _word_count(content) < _MIN_CONTENT_WORDS:
            continue

        section_title = first_heading or page_title or config.source_name
        discovered_links = _extract_links(container, page.url, config)
        if _is_listing_like_page(content, discovered_links):
            continue

        document = ParsedDocument(
            source_name=config.source_name,
            source_url=page.url,
            section_title=section_title,
            content=content,
            discovered_links=discovered_links,
        )
        if len(document.content) > best_length:
            best_document = document
            best_length = len(document.content)

    return best_document


def _redirect_chain_hosts(requested_url: str, response: httpx.Response) -> list[str]:
    hosts = [urlparse(requested_url).netloc.lower()]
    hosts.extend(urlparse(str(item.url)).netloc.lower() for item in response.history)
    hosts.append(urlparse(str(response.url)).netloc.lower())
    return [host for host in hosts if host]


def _is_allowed_redirect(requested_url: str, response: httpx.Response, config: SourceConfig) -> bool:
    final_url = str(response.url)
    if not _is_allowed_url(final_url, config):
        return False

    hosts = _redirect_chain_hosts(requested_url, response)
    host_changes = sum(1 for left, right in zip(hosts, hosts[1:]) if left != right)
    if host_changes > 1:
        allowed_chain_hosts = config.allowed_hosts | {
            host.lower() for host in config.redirect_passthrough_hosts
        }
        if not all(host in allowed_chain_hosts for host in hosts):
            return False
    return True


async def _sleep_backoff(attempt: int) -> None:
    delay = _INITIAL_BACKOFF_SECONDS * (2 ** (attempt - 1)) + random.uniform(0, 0.1)
    await asyncio.sleep(delay)


def _api_error_status_code(exc: APIError) -> int | None:
    for attr in ("code", "status_code", "status"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    if isinstance(getattr(exc, "args", None), tuple) and exc.args:
        first = exc.args[0]
        if isinstance(first, dict):
            for key in ("code", "status_code", "status"):
                value = first.get(key)
                if isinstance(value, int):
                    return value
                if isinstance(value, str) and value.isdigit():
                    return int(value)
    return None


def _is_retryable_api_error(exc: APIError) -> bool:
    status_code = _api_error_status_code(exc)
    if status_code in _RETRYABLE_API_STATUS_CODES:
        return True
    message = str(exc).lower()
    return any(token in message for token in ("timeout", "tempor", "rate limit", "bad gateway", "service unavailable", "gateway"))


def _classify_fetch_error(exc: Exception, config: SourceConfig) -> tuple[str, str] | None:
    message = str(exc).lower()
    if (
        config.known_failure_label == "environment_blocked_tls"
        and isinstance(exc, (httpx.ConnectError, httpx.ReadError))
        and "certificate verify failed" in message
    ):
        return ("environment_blocked", "tls_certificate_verification_failed")
    return None


def _is_certificate_verification_error(exc: Exception) -> bool:
    return (
        isinstance(exc, (httpx.ConnectError, httpx.ReadError))
        and "certificate verify failed" in str(exc).lower()
    )


def _build_tls_fallback_context(config: SourceConfig) -> ssl.SSLContext | None:
    if config.tls_fallback_strategy != "system_trust_store":
        return None

    try:
        import truststore
    except ImportError:
        logger.warning(
            "TLS fallback requested but truststore is unavailable source=%s",
            config.source_name,
        )
        return None

    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


async def _fetch_with_tls_fallback(
    client: httpx.AsyncClient,
    url: str,
    config: SourceConfig,
) -> httpx.Response | None:
    verify_context = _build_tls_fallback_context(config)
    if verify_context is None:
        return None

    logger.warning(
        "Retrying fetch with TLS fallback source=%s url=%s strategy=%s",
        config.source_name,
        url,
        config.tls_fallback_strategy,
    )
    async with httpx.AsyncClient(
        headers=dict(client.headers),
        timeout=client.timeout,
        verify=verify_context,
    ) as fallback_client:
        response = await fallback_client.get(url, follow_redirects=True)
        response.raise_for_status()
        return response


async def _run_supabase_operation(
    operation_name: str,
    run_operation,
    *,
    rows: int | None = None,
    batch_start: int | None = None,
) -> Any:
    active_client = _get_supabase_client()
    for attempt in range(1, _MAX_INSERT_ATTEMPTS + 1):
        try:
            return await asyncio.to_thread(run_operation, active_client)
        except (httpx.ReadError, httpx.WriteError, httpx.ConnectError, httpx.RemoteProtocolError, httpx.TimeoutException) as exc:
            if attempt == _MAX_INSERT_ATTEMPTS:
                raise
            logger.warning(
                "Retrying Supabase %s attempt=%s rows=%s batch_start=%s error=%s message=%s",
                operation_name,
                attempt,
                rows,
                batch_start,
                type(exc).__name__,
                str(exc),
            )
            active_client = _reset_supabase_client()
            await _sleep_backoff(attempt)
        except APIError as exc:
            if attempt == _MAX_INSERT_ATTEMPTS or not _is_retryable_api_error(exc):
                raise
            logger.warning(
                "Retrying Supabase %s attempt=%s rows=%s batch_start=%s error=%s message=%s",
                operation_name,
                attempt,
                rows,
                batch_start,
                type(exc).__name__,
                str(exc),
            )
            active_client = _reset_supabase_client()
            await _sleep_backoff(attempt)


async def _fetch_page(
    client: httpx.AsyncClient,
    url: str,
    robots_cache: RobotsPolicyCache,
    config: SourceConfig,
) -> FetchedPage | None:
    allowed = await robots_cache.can_fetch(client, url)
    if not allowed:
        logger.info("Skipping robots-blocked url=%s", url)
        return None

    response: httpx.Response | None = None
    for attempt in range(1, _MAX_FETCH_ATTEMPTS + 1):
        try:
            response = await client.get(url, follow_redirects=True)
            response.raise_for_status()
            break
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            if attempt < _MAX_FETCH_ATTEMPTS and status_code in {408, 429, 500, 502, 503, 504}:
                logger.warning(
                    "Retrying fetch url=%s attempt=%s status=%s",
                    url,
                    attempt,
                    status_code,
                )
                await _sleep_backoff(attempt)
                continue
            logger.exception("Failed to fetch url=%s", url)
            return None
        except (httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError, httpx.TimeoutException) as exc:
            if attempt < _MAX_FETCH_ATTEMPTS:
                logger.warning("Retrying fetch url=%s attempt=%s", url, attempt)
                await _sleep_backoff(attempt)
                continue
            if _is_certificate_verification_error(exc):
                try:
                    response = await _fetch_with_tls_fallback(client, url, config)
                except httpx.HTTPStatusError:
                    logger.exception("Failed TLS fallback fetch url=%s", url)
                    return None
                except (httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError, httpx.TimeoutException):
                    logger.exception("Failed TLS fallback fetch url=%s", url)
                else:
                    if response is not None:
                        break
            classified = _classify_fetch_error(exc, config)
            if classified is not None:
                status, detail = classified
                logger.error(
                    "Classified source fetch failure source=%s url=%s status=%s detail=%s",
                    config.source_name,
                    url,
                    status,
                    detail,
                )
                raise SourceFetchBlocked(status, detail) from exc
            logger.exception("Failed to fetch url=%s", url)
            return None
        finally:
            await asyncio.sleep(_REQUEST_DELAY_SECONDS)

    if response is None:
        return None

    if not _is_allowed_redirect(url, response, config):
        logger.info("Skipping redirect-out-of-scope requested_url=%s final_url=%s", url, response.url)
        return None

    requested_host = urlparse(url).netloc.lower()
    final_host = urlparse(str(response.url)).netloc.lower()
    if requested_host != final_host:
        logger.info("Following cross-host redirect requested_url=%s final_url=%s", url, response.url)

    content_type = response.headers.get("content-type", "")
    if "text/html" not in content_type:
        logger.info("Skipping non-HTML url=%s content_type=%s", url, content_type)
        return None

    return FetchedPage(url=_normalize_url(str(response.url)), html=response.text)


async def _select_existing_chunk_indices(client: Client, source_url: str) -> set[int]:
    def _run(active_client: Client) -> Any:
        return (
            active_client.table("corpus_chunks")
            .select("chunk_index")
            .eq("source_url", source_url)
            .execute()
        )

    response = await _run_supabase_operation(
        "select",
        _run,
        rows=1,
    )
    return {
        int(item["chunk_index"])
        for item in (response.data or [])
        if item.get("chunk_index") is not None
    }


async def _insert_chunk_rows(client: Client, rows: list[CorpusChunkRow]) -> int:
    if not rows:
        return 0

    inserted_count = 0
    payload = [row.model_dump() for row in rows]
    for batch_start in range(0, len(payload), _MAX_INSERT_BATCH_SIZE):
        batch = payload[batch_start : batch_start + _MAX_INSERT_BATCH_SIZE]
        def _run(active_client: Client) -> Any:
            return active_client.table("corpus_chunks").insert(batch).execute()

        await _run_supabase_operation(
            "insert",
            _run,
            rows=len(batch),
            batch_start=batch_start,
        )
        inserted_count += len(batch)

    return inserted_count


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

    headers = _build_client_headers(config)
    timeout = httpx.Timeout(20.0, connect=10.0)
    async with httpx.AsyncClient(headers=headers, timeout=timeout) as http_client:
        while queue and stats.pages_fetched < page_limit:
            url = queue.popleft()
            try:
                page = await _fetch_page(http_client, url, robots_cache, config)
            except SourceFetchBlocked as exc:
                stats.pages_skipped += 1
                stats.final_status = exc.status
                stats.status_detail = exc.detail
                break
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
    if stats.final_status != "completed":
        logger.info(
            "Source verdict source=%s final_status=%s detail=%s",
            stats.source_name,
            stats.final_status,
            stats.status_detail,
        )
        print(
            f"Source verdict for {stats.source_name}: "
            f"{stats.final_status} ({stats.status_detail})"
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
