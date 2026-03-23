import asyncio

import httpx
from bs4 import BeautifulSoup
from postgrest.exceptions import APIError
from rag.ingest import CorpusChunkRow

from rag.ingest import (
    FetchedPage,
    RobotsPolicyCache,
    SourceConfig,
    _fetch_page,
    _insert_chunk_rows,
    _is_allowed_redirect,
    _is_allowed_url,
    _parse_document,
    _select_existing_chunk_indices,
    _strip_noise,
)


def _make_config(**overrides):
    base = {
        "key": "docs",
        "base_url": "https://docs.example.com",
        "start_paths": ["/docs/start"],
        "source_name": "Docs",
        "max_pages": 10,
    }
    base.update(overrides)
    return SourceConfig(**base)


def test_same_host_links_allowed_outside_seed_prefix():
    config = _make_config()
    assert _is_allowed_url("https://docs.example.com/reference/other-page", config)


def test_blocked_noise_paths_are_rejected():
    config = _make_config(blocked_path_substrings=["/blog/"])
    assert not _is_allowed_url("https://docs.example.com/blog/post", config)


def test_allowed_redirect_host_is_accepted():
    config = _make_config(redirect_allowed_hosts=["newdocs.example.com"])
    initial_request = httpx.Request("GET", "https://docs.example.com/docs/start")
    redirect_request = httpx.Request("GET", "https://newdocs.example.com/docs/final")
    history = [httpx.Response(302, request=initial_request, headers={"location": "https://newdocs.example.com/docs/final"})]
    response = httpx.Response(200, request=redirect_request, history=history, headers={"content-type": "text/html"})
    assert _is_allowed_redirect("https://docs.example.com/docs/start", response, config)


def test_unrelated_redirect_host_is_rejected():
    config = _make_config()
    initial_request = httpx.Request("GET", "https://docs.example.com/docs/start")
    redirect_request = httpx.Request("GET", "https://evil.example.org/docs/final")
    history = [httpx.Response(302, request=initial_request, headers={"location": "https://evil.example.org/docs/final"})]
    response = httpx.Response(200, request=redirect_request, history=history, headers={"content-type": "text/html"})
    assert not _is_allowed_redirect("https://docs.example.com/docs/start", response, config)


def test_strip_noise_handles_malformed_attrs():
    soup = BeautifulSoup("<body><div class='content'><nav>Nav</nav><section id='main'>Text</section></div></body>", "html.parser")
    container = soup.find("div")
    nav = soup.find("nav")
    assert container is not None
    assert nav is not None
    nav.attrs = None
    _strip_noise(container)


def test_parse_document_skips_thin_page():
    config = _make_config()
    page = FetchedPage(
        url="https://docs.example.com/docs/start",
        html="<html><body><main><h1>Title</h1><p>Too short.</p></main></body></html>",
    )
    assert _parse_document(page, config) is None


def test_parse_document_keeps_substantive_page():
    config = _make_config()
    paragraph = " ".join(["content"] * 250)
    page = FetchedPage(
        url="https://docs.example.com/docs/start",
        html=f"<html><body><main><h1>Guide</h1><p>{paragraph}</p></main></body></html>",
    )
    document = _parse_document(page, config)
    assert document is not None
    assert document.section_title == "Guide"


def test_parse_document_uses_role_main_container():
    config = _make_config()
    paragraph = " ".join(["content"] * 250)
    page = FetchedPage(
        url="https://docs.example.com/docs/start",
        html=f"<html><body><div role='main'><h1>Guide</h1><p>{paragraph}</p></div></body></html>",
    )
    document = _parse_document(page, config)
    assert document is not None
    assert document.section_title == "Guide"


def test_insert_retries_after_read_error(monkeypatch):
    calls = {"count": 0}

    class DummyRequest:
        def execute(self):
            calls["count"] += 1
            if calls["count"] == 1:
                raise httpx.ReadError("boom")
            return object()

    class DummyTable:
        def insert(self, payload):
            return DummyRequest()

    class DummyClient:
        def table(self, name):
            assert name == "corpus_chunks"
            return DummyTable()

    monkeypatch.setattr("rag.ingest._get_supabase_client", lambda: DummyClient())
    monkeypatch.setattr("rag.ingest._sleep_backoff", lambda attempt: asyncio.sleep(0))

    rows = [
        CorpusChunkRow(
            source_name="Docs",
            source_url="https://docs.example.com/a",
            section_title="Section",
            content="Body",
            embedding=[0.1, 0.2],
            chunk_index=0,
        )
    ]
    count = asyncio.run(_insert_chunk_rows(DummyClient(), rows))
    assert count == 1
    assert calls["count"] == 2


def test_insert_retries_after_write_error(monkeypatch):
    calls = {"count": 0}

    class DummyRequest:
        def execute(self):
            calls["count"] += 1
            if calls["count"] == 1:
                raise httpx.WriteError("boom")
            return object()

    class DummyTable:
        def insert(self, payload):
            return DummyRequest()

    class DummyClient:
        def table(self, name):
            assert name == "corpus_chunks"
            return DummyTable()

    monkeypatch.setattr("rag.ingest._get_supabase_client", lambda: DummyClient())
    monkeypatch.setattr("rag.ingest._sleep_backoff", lambda attempt: asyncio.sleep(0))

    rows = [
        CorpusChunkRow(
            source_name="Docs",
            source_url="https://docs.example.com/a",
            section_title="Section",
            content="Body",
            embedding=[0.1, 0.2],
            chunk_index=0,
        )
    ]
    count = asyncio.run(_insert_chunk_rows(DummyClient(), rows))
    assert count == 1
    assert calls["count"] == 2


def test_insert_retries_after_retryable_api_error(monkeypatch):
    calls = {"count": 0, "resets": 0}

    class DummyRequest:
        def execute(self):
            calls["count"] += 1
            if calls["count"] == 1:
                raise APIError({"status": 503, "message": "service unavailable"})
            return object()

    class DummyTable:
        def insert(self, payload):
            return DummyRequest()

    class DummyClient:
        def table(self, name):
            assert name == "corpus_chunks"
            return DummyTable()

    monkeypatch.setattr("rag.ingest._sleep_backoff", lambda attempt: asyncio.sleep(0))
    monkeypatch.setattr("rag.ingest._get_supabase_client", lambda: DummyClient())

    def reset_client():
        calls["resets"] += 1
        return DummyClient()

    monkeypatch.setattr("rag.ingest._reset_supabase_client", reset_client)

    rows = [
        CorpusChunkRow(
            source_name="Docs",
            source_url="https://docs.example.com/a",
            section_title="Section",
            content="Body",
            embedding=[0.1, 0.2],
            chunk_index=0,
        )
    ]
    count = asyncio.run(_insert_chunk_rows(DummyClient(), rows))
    assert count == 1
    assert calls["count"] == 2
    assert calls["resets"] == 1


def test_insert_fails_fast_on_non_retryable_api_error(monkeypatch):
    class DummyRequest:
        def execute(self):
            raise APIError({"status": 400, "message": "bad request"})

    class DummyTable:
        def insert(self, payload):
            return DummyRequest()

    class DummyClient:
        def table(self, name):
            return DummyTable()

    monkeypatch.setattr("rag.ingest._sleep_backoff", lambda attempt: asyncio.sleep(0))
    monkeypatch.setattr("rag.ingest._get_supabase_client", lambda: DummyClient())
    monkeypatch.setattr("rag.ingest._reset_supabase_client", lambda: DummyClient())

    rows = [
        CorpusChunkRow(
            source_name="Docs",
            source_url="https://docs.example.com/a",
            section_title="Section",
            content="Body",
            embedding=[0.1, 0.2],
            chunk_index=0,
        )
    ]
    try:
        asyncio.run(_insert_chunk_rows(DummyClient(), rows))
    except APIError as exc:
        assert "bad request" in str(exc).lower()
    else:
        raise AssertionError("Expected APIError to be raised")


def test_select_retries_after_read_error(monkeypatch):
    calls = {"count": 0, "resets": 0}

    class DummyRequest:
        def execute(self):
            calls["count"] += 1
            if calls["count"] == 1:
                raise httpx.ReadError("boom")

            class Response:
                data = [{"chunk_index": 0}, {"chunk_index": 2}]

            return Response()

    class DummyFilter:
        def eq(self, key, value):
            assert key == "source_url"
            return DummyRequest()

    class DummyTable:
        def select(self, field):
            assert field == "chunk_index"
            return DummyFilter()

    class DummyClient:
        def table(self, name):
            assert name == "corpus_chunks"
            return DummyTable()

    monkeypatch.setattr("rag.ingest._sleep_backoff", lambda attempt: asyncio.sleep(0))
    monkeypatch.setattr("rag.ingest._get_supabase_client", lambda: DummyClient())

    def reset_client():
        calls["resets"] += 1
        return DummyClient()

    monkeypatch.setattr("rag.ingest._reset_supabase_client", reset_client)

    result = asyncio.run(_select_existing_chunk_indices(DummyClient(), "https://docs.example.com/a"))
    assert result == {0, 2}
    assert calls["count"] == 2
    assert calls["resets"] == 1


def test_fetch_retries_after_transient_error(monkeypatch):
    request = httpx.Request("GET", "https://docs.example.com/docs/start")
    response = httpx.Response(200, request=request, headers={"content-type": "text/html"}, text="<html></html>")

    class DummyClient:
        def __init__(self):
            self.calls = 0

        async def get(self, url, follow_redirects=True):
            self.calls += 1
            if self.calls == 1:
                raise httpx.ReadError("transient")
            return response

    monkeypatch.setattr("rag.ingest._sleep_backoff", lambda attempt: asyncio.sleep(0))

    async def run_test():
        client = DummyClient()
        robots = RobotsPolicyCache()
        robots._policies["docs.example.com"] = type("Policy", (), {"can_fetch": lambda self, user_agent, url: True})()
        page = await _fetch_page(client, "https://docs.example.com/docs/start", robots, _make_config())
        assert page is not None
        assert client.calls == 2

    asyncio.run(run_test())
