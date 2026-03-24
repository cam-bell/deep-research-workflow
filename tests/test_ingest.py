import asyncio

import httpx
from bs4 import BeautifulSoup
from postgrest.exceptions import APIError
from rag.ingest import CorpusChunkRow

from rag.ingest import (
    FetchedPage,
    RobotsPolicyCache,
    SOURCES,
    SourceConfig,
    SourceFetchBlocked,
    _build_client_headers,
    _build_tls_fallback_context,
    _classify_fetch_error,
    _fetch_page,
    _fetch_with_tls_fallback,
    _insert_chunk_rows,
    _is_allowed_redirect,
    _is_allowed_url,
    _is_listing_like_page,
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


def test_cloudflare_tag_and_author_urls_are_rejected():
    config = _make_config(
        base_url=None,
        start_paths=[],
        urls=["https://blog.cloudflare.com/tag/engineering/"],
        blocked_path_substrings=["/tag/", "/author/"],
    )
    assert not _is_allowed_url("https://blog.cloudflare.com/tag/rust/", config)
    assert not _is_allowed_url("https://blog.cloudflare.com/author/example/", config)


def test_cloudflare_article_urls_are_allowed():
    config = _make_config(
        base_url=None,
        start_paths=[],
        urls=["https://blog.cloudflare.com/tag/engineering/"],
        blocked_path_substrings=["/tag/", "/author/"],
    )
    assert _is_allowed_url(
        "https://blog.cloudflare.com/ecdysis-rust-graceful-restarts/",
        config,
    )


def test_netflix_article_urls_are_allowed():
    config = _make_config(
        base_url=None,
        start_paths=[],
        urls=[
            "https://netflixtechblog.com/scaling-global-storytelling-modernizing-localization-analytics-at-netflix-816f47290641",
        ],
        blocked_path_substrings=["/tagged/", "/author/", "/followers"],
    )
    assert _is_allowed_url(
        "https://netflixtechblog.com/optimizing-recommendation-systems-with-jdks-vector-api-30d2830401ec",
        config,
    )
    assert not _is_allowed_url(
        "https://netflixtechblog.com/tagged/performance",
        config,
    )


def test_meta_article_urls_are_allowed():
    config = _make_config(
        base_url=None,
        start_paths=[],
        urls=[
            "https://engineering.fb.com/category/developer-tools/",
        ],
        blocked_path_substrings=["/author/", "/jobs", "/careers", "/videos", "/feed", "/rss"],
    )
    assert _is_allowed_url(
        "https://engineering.fb.com/2026/03/09/security/how-advanced-browsing-protection-works-in-messenger/",
        config,
    )


def test_meta_non_article_routes_are_rejected():
    config = _make_config(
        base_url=None,
        start_paths=[],
        urls=[
            "https://engineering.fb.com/category/developer-tools/",
        ],
        blocked_path_substrings=["/author/", "/jobs", "/careers", "/videos", "/feed", "/rss"],
    )
    assert not _is_allowed_url("https://engineering.fb.com/author/example/", config)
    assert not _is_allowed_url("https://engineering.fb.com/videos", config)
    assert not _is_allowed_url("https://www.metacareers.com/jobs/123", config)


def test_anthropic_docs_stay_inside_docs_tree():
    config = _make_config(
        base_url="https://platform.claude.com",
        start_paths=["docs/en/home"],
        redirect_allowed_hosts=["docs.anthropic.com"],
        blocked_path_substrings=[
            "/settings",
            "/workbench",
            "/dashboard",
            "/usage",
            "/cost",
            "/cookbook",
            "/cookbooks",
            "/cdn-cgi/",
        ],
        allowed_path_prefixes=["/docs/en/", "/en/docs/"],
    )
    assert _is_allowed_url("https://platform.claude.com/docs/en/api/messages", config)
    assert _is_allowed_url("https://docs.anthropic.com/en/docs/models-overview", config)
    assert not _is_allowed_url("https://platform.claude.com/settings/keys", config)
    assert not _is_allowed_url("https://platform.claude.com/workbench", config)
    assert not _is_allowed_url("https://platform.claude.com/cookbook/tool-use-calculator-tool", config)


def test_netflix_article_page_discovers_canonical_article_links():
    config = _make_config(
        base_url=None,
        start_paths=[],
        urls=[
            "https://netflixtechblog.com/scaling-global-storytelling-modernizing-localization-analytics-at-netflix-816f47290641",
        ],
        blocked_path_substrings=["/tagged/", "/author/", "/followers"],
    )
    paragraph = " ".join(["content"] * 260)
    page = FetchedPage(
        url="https://netflixtechblog.com/scaling-global-storytelling-modernizing-localization-analytics-at-netflix-816f47290641",
        html=(
            "<html><body><main>"
            "<h1>Scaling Global Storytelling</h1>"
            f"<p>{paragraph}</p>"
            "<a href='https://netflixtechblog.com/optimizing-recommendation-systems-with-jdks-vector-api-30d2830401ec?source=collection_home_page----2615bd06b42e-----0-----------------------------------'>Next</a>"
            "<a href='https://netflixtechblog.com/mediafm-the-multimodal-ai-foundation-for-media-understanding-at-netflix-e8c28df82e2d?source=collection_home_page----2615bd06b42e-----1-----------------------------------'>Related</a>"
            "<a href='https://netflixtechblog.com/tagged/performance'>Tag</a>"
            "<a href='https://netflixtechblog.com/followers'>Followers</a>"
            "</main></body></html>"
        ),
    )
    document = _parse_document(page, config)
    assert document is not None
    assert document.discovered_links == [
        "https://netflixtechblog.com/optimizing-recommendation-systems-with-jdks-vector-api-30d2830401ec",
        "https://netflixtechblog.com/mediafm-the-multimodal-ai-foundation-for-media-understanding-at-netflix-e8c28df82e2d",
    ]


def test_meta_article_page_discovers_canonical_article_links():
    config = _make_config(
        base_url=None,
        start_paths=[],
        urls=[
            "https://engineering.fb.com/category/developer-tools/",
        ],
        blocked_path_substrings=["/author/", "/jobs", "/careers", "/videos", "/feed", "/rss"],
    )
    paragraph = " ".join(["content"] * 260)
    page = FetchedPage(
        url="https://engineering.fb.com/2026/03/17/developer-tools/ranking-engineer-agent-rea-autonomous-ai-system-accelerating-meta-ads-ranking-innovation/",
        html=(
            "<html><body><article>"
            "<h1>Ranking Engineer Agent</h1>"
            f"<p>{paragraph}</p>"
            "<a href='https://engineering.fb.com/2026/03/09/security/how-advanced-browsing-protection-works-in-messenger/'>Security</a>"
            "<a href='https://engineering.fb.com/2026/03/02/video-engineering/ffmpeg-at-meta-media-processing-at-scale/'>Video</a>"
            "<a href='https://engineering.fb.com/category/security/'>Category</a>"
            "<a href='https://engineering.fb.com/author/example/'>Author</a>"
            "<a href='https://www.metacareers.com/jobs/123'>Jobs</a>"
            "</article></body></html>"
        ),
    )
    parse_result = _parse_document(page, config)
    assert parse_result.document is not None
    assert parse_result.discovered_links == [
        "https://engineering.fb.com/2026/03/09/security/how-advanced-browsing-protection-works-in-messenger",
        "https://engineering.fb.com/2026/03/02/video-engineering/ffmpeg-at-meta-media-processing-at-scale",
        "https://engineering.fb.com/category/security",
    ]


def test_listing_page_returns_links_even_when_not_chunked():
    config = _make_config()
    links = "".join(
        f"<li><a href='/docs/article-{index}'>Article {index}</a></li>"
        for index in range(20)
    )
    page = FetchedPage(
        url="https://docs.example.com/docs/start",
        html=(
            "<html><body><main><h1>Engineering</h1>"
            "<p>" + " ".join(["summary"] * 220) + "</p>"
            f"<ul>{links}</ul>"
            "</main></body></html>"
        ),
    )
    parse_result = _parse_document(page, config)
    assert parse_result.document is None
    assert parse_result.skip_reason == "listing_page"
    assert len(parse_result.discovered_links) == 20


def test_meta_category_page_returns_article_links_without_chunking():
    config = _make_config(
        base_url=None,
        start_paths=[],
        urls=["https://engineering.fb.com/category/developer-tools/"],
        blocked_path_substrings=["/author/", "/jobs", "/careers", "/videos", "/feed", "/rss"],
    )
    page = FetchedPage(
        url="https://engineering.fb.com/category/developer-tools/",
        html=(
            "<html><body><main><h1>Developer Tools</h1>"
            "<p>" + " ".join(["summary"] * 220) + "</p>"
            "<a href='https://engineering.fb.com/2026/03/17/developer-tools/ranking-engineer-agent-rea-autonomous-ai-system-accelerating-meta-ads-ranking-innovation/'>REA</a>"
            "<a href='https://engineering.fb.com/2026/02/11/developer-tools/the-death-of-traditional-testing-agentic-development-jit-testing-revival/'>Testing</a>"
            "<a href='https://engineering.fb.com/category/security/'>Category</a>"
            "<a href='https://engineering.fb.com/author/example/'>Author</a>"
            "<a href='https://www.metacareers.com/jobs/123'>Jobs</a>"
            + "".join(
                f"<a href='https://engineering.fb.com/2026/01/{index:02d}/developer-tools/tool-{index}/'>Tool {index}</a>"
                for index in range(1, 15)
            )
            + "</main></body></html>"
        ),
    )
    parse_result = _parse_document(page, config)
    assert parse_result.document is None
    assert parse_result.skip_reason == "listing_page"
    assert "https://engineering.fb.com/2026/03/17/developer-tools/ranking-engineer-agent-rea-autonomous-ai-system-accelerating-meta-ads-ranking-innovation" in parse_result.discovered_links
    assert "https://engineering.fb.com/category/security" in parse_result.discovered_links


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


def test_trusted_passthrough_redirect_chain_is_accepted():
    config = _make_config(
        base_url=None,
        start_paths=[],
        urls=["https://netflixtechblog.com/"],
        redirect_passthrough_hosts=["medium.com"],
    )
    initial_request = httpx.Request("GET", "https://netflixtechblog.com/")
    medium_request = httpx.Request("GET", "https://medium.com/m/global-identity-2")
    final_request = httpx.Request("GET", "https://netflixtechblog.com/?gi=abc")
    history = [
        httpx.Response(307, request=initial_request, headers={"location": "https://medium.com/m/global-identity-2"}),
        httpx.Response(307, request=medium_request, headers={"location": "https://netflixtechblog.com/?gi=abc"}),
    ]
    response = httpx.Response(
        200,
        request=final_request,
        history=history,
        headers={"content-type": "text/html"},
    )
    assert _is_allowed_redirect("https://netflixtechblog.com/", response, config)


def test_untrusted_passthrough_redirect_chain_is_rejected():
    config = _make_config(
        base_url=None,
        start_paths=[],
        urls=["https://netflixtechblog.com/"],
    )
    initial_request = httpx.Request("GET", "https://netflixtechblog.com/")
    medium_request = httpx.Request("GET", "https://medium.com/m/global-identity-2")
    final_request = httpx.Request("GET", "https://netflixtechblog.com/?gi=abc")
    history = [
        httpx.Response(307, request=initial_request, headers={"location": "https://medium.com/m/global-identity-2"}),
        httpx.Response(307, request=medium_request, headers={"location": "https://netflixtechblog.com/?gi=abc"}),
    ]
    response = httpx.Response(
        200,
        request=final_request,
        history=history,
        headers={"content-type": "text/html"},
    )
    assert not _is_allowed_redirect("https://netflixtechblog.com/", response, config)


def test_strip_noise_handles_malformed_attrs():
    soup = BeautifulSoup("<body><div class='content'><nav>Nav</nav><section id='main'>Text</section></div></body>", "html.parser")
    container = soup.find("div")
    nav = soup.find("nav")
    assert container is not None
    assert nav is not None
    nav.attrs = None
    _strip_noise(container)


def test_strip_noise_removes_cookie_and_consent_selectors():
    soup = BeautifulSoup(
        (
            "<main>"
            "<div class='cookie-banner'>Cookie banner</div>"
            "<div id='cookie-notice'>Cookie notice</div>"
            "<div class='consent'>Consent text</div>"
            "<div id='consent-banner'>Consent banner</div>"
            "<div aria-label='cookie preferences'>Cookie preferences</div>"
            "<article>Real content</article>"
            "</main>"
        ),
        "html.parser",
    )
    container = soup.main
    assert container is not None

    _strip_noise(container)

    text = container.get_text(" ", strip=True)
    assert "Cookie banner" not in text
    assert "Cookie notice" not in text
    assert "Consent text" not in text
    assert "Consent banner" not in text
    assert "Cookie preferences" not in text
    assert "Real content" in text


def test_parse_document_skips_thin_page():
    config = _make_config()
    page = FetchedPage(
        url="https://docs.example.com/docs/start",
        html="<html><body><main><h1>Title</h1><p>Too short.</p></main></body></html>",
    )
    parse_result = _parse_document(page, config)
    assert parse_result.document is None
    assert parse_result.skip_reason == "thin_page"


def test_parse_document_keeps_substantive_page():
    config = _make_config()
    paragraph = " ".join(["content"] * 250)
    page = FetchedPage(
        url="https://docs.example.com/docs/start",
        html=f"<html><body><main><h1>Guide</h1><p>{paragraph}</p></main></body></html>",
    )
    parse_result = _parse_document(page, config)
    assert parse_result.document is not None
    assert parse_result.document.section_title == "Guide"


def test_parse_document_truncates_at_noise_section_terms():
    config = _make_config()
    page = FetchedPage(
        url="https://docs.example.com/docs/start",
        html=(
            "<html><body><main>"
            "<h1>Meta article</h1>"
            "<p>" + " ".join(["content"] * 260) + "</p>"
            "<h2>Share this</h2>"
            "<p>Read More in Security</p>"
            "<p>Acknowledgments</p>"
            "</main></body></html>"
        ),
    )
    parse_result = _parse_document(page, config)
    assert parse_result.document is not None
    assert "Share this" not in parse_result.document.content
    assert "Read More in Security" not in parse_result.document.content
    assert "Acknowledgments" not in parse_result.document.content


def test_github_article_truncates_at_newsletter_footer_noise():
    config = _make_config(
        key="github-rfcs",
        base_url=None,
        start_paths=[],
        urls=["https://github.blog/engineering/"],
        blocked_path_substrings=["/pricing", "/login", "/account", "/tag/", "/author/", "/categories/"],
        allowed_path_prefixes=["/engineering/"],
    )
    page = FetchedPage(
        url="https://github.blog/engineering/infrastructure/how-github-engineers-tackle-platform-problems/",
        html=(
            "<html><body><main>"
            "<h1>How GitHub engineers tackle platform problems</h1>"
            "<p>Written by</p>"
            "<p>" + " ".join(["content"] * 260) + "</p>"
            "<h2>Share:</h2>"
            "<ul><li>X</li><li>LinkedIn</li></ul>"
            "<h2>We do newsletters, too</h2>"
            "<p>Subscribe for updates</p>"
            "<h2>Site-wide Links</h2>"
            "<p>Pricing Docs Careers</p>"
            "</main></body></html>"
        ),
    )
    parse_result = _parse_document(page, config)
    assert parse_result.document is not None
    assert "Share:" not in parse_result.document.content
    assert "Subscribe for updates" not in parse_result.document.content
    assert "Site-wide Links" not in parse_result.document.content


def test_github_article_excludes_tags_related_and_more_sections():
    config = _make_config(
        key="github-rfcs",
        base_url=None,
        start_paths=[],
        urls=["https://github.blog/engineering/"],
        blocked_path_substrings=["/pricing", "/login", "/account", "/tag/", "/author/", "/categories/"],
        allowed_path_prefixes=["/engineering/"],
    )
    page = FetchedPage(
        url="https://github.blog/engineering/platform-security/defense-systems-at-scale/",
        html=(
            "<html><body><article>"
            "<h1>Defense systems at scale</h1>"
            "<p>" + " ".join(["content"] * 260) + "</p>"
            "<h2>Tags:</h2>"
            "<ul><li>security</li><li>platform</li></ul>"
            "<h2>Related posts</h2>"
            "<p>Another post</p>"
            "<h2>More on</h2>"
            "<p>Platform security</p>"
            "</article></body></html>"
        ),
    )
    parse_result = _parse_document(page, config)
    assert parse_result.document is not None
    assert "Tags:" not in parse_result.document.content
    assert "Related posts" not in parse_result.document.content
    assert "Platform security" not in parse_result.document.content


def test_parse_document_uses_role_main_container():
    config = _make_config()
    paragraph = " ".join(["content"] * 250)
    page = FetchedPage(
        url="https://docs.example.com/docs/start",
        html=f"<html><body><div role='main'><h1>Guide</h1><p>{paragraph}</p></div></body></html>",
    )
    parse_result = _parse_document(page, config)
    assert parse_result.document is not None
    assert parse_result.document.section_title == "Guide"


def test_listing_like_pages_are_skipped():
    config = _make_config()
    links = "".join(
        f"<li><a href='/docs/article-{index}'>Article {index}</a></li>"
        for index in range(20)
    )
    page = FetchedPage(
        url="https://docs.example.com/docs/start",
        html=(
            "<html><body><main><h1>Engineering</h1>"
            "<p>" + " ".join(["summary"] * 220) + "</p>"
            f"<ul>{links}</ul>"
            "</main></body></html>"
        ),
    )
    parse_result = _parse_document(page, config)
    assert parse_result.document is None
    assert parse_result.skip_reason == "listing_page"
    assert len(parse_result.discovered_links) == 20


def test_article_like_pages_are_kept_even_with_links():
    config = _make_config()
    links = "".join(
        f"<li><a href='/docs/article-{index}'>Related {index}</a></li>"
        for index in range(4)
    )
    page = FetchedPage(
        url="https://docs.example.com/docs/start",
        html=(
            "<html><body><main><h1>Engineering</h1>"
            "<p>" + " ".join(["content"] * 380) + "</p>"
            f"<ul>{links}</ul>"
            "</main></body></html>"
        ),
    )
    parse_result = _parse_document(page, config)
    assert parse_result.document is not None
    assert parse_result.document.section_title == "Engineering"


def test_github_engineering_landing_page_is_discovery_only():
    config = _make_config(
        key="github-rfcs",
        base_url=None,
        start_paths=[],
        urls=["https://github.blog/engineering/"],
        blocked_path_substrings=["/pricing", "/login", "/account", "/tag/", "/author/", "/categories/"],
        allowed_path_prefixes=["/engineering/"],
    )
    links = "".join(
        f"<a href='https://github.blog/engineering/infrastructure/article-{index}/'>Article {index}</a>"
        for index in range(1, 14)
    )
    page = FetchedPage(
        url="https://github.blog/engineering/",
        html=(
            "<html><body><main>"
            "<h1>Engineering</h1>"
            "<p>" + " ".join(["summary"] * 260) + "</p>"
            "<h2>Featured</h2>"
            f"{links}"
            "</main></body></html>"
        ),
    )
    parse_result = _parse_document(page, config)
    assert parse_result.document is None
    assert parse_result.skip_reason == "listing_page"
    assert len(parse_result.discovered_links) == 13


def test_github_subcategory_page_is_discovery_only_even_when_substantive():
    config = _make_config(
        key="github-rfcs",
        base_url=None,
        start_paths=[],
        urls=["https://github.blog/engineering/"],
        blocked_path_substrings=["/pricing", "/login", "/account", "/tag/", "/author/", "/categories/"],
        allowed_path_prefixes=["/engineering/"],
    )
    links = "".join(
        f"<a href='https://github.blog/engineering/infrastructure/article-{index}/'>Article {index}</a>"
        for index in range(1, 10)
    )
    page = FetchedPage(
        url="https://github.blog/engineering/infrastructure/",
        html=(
            "<html><body><main>"
            "<h1>Infrastructure</h1>"
            "<p>" + " ".join(["summary"] * 420) + "</p>"
            "<h2>Featured</h2>"
            f"{links}"
            "</main></body></html>"
        ),
    )
    parse_result = _parse_document(page, config)
    assert parse_result.document is None
    assert parse_result.skip_reason == "listing_page"
    assert len(parse_result.discovered_links) == 9


def test_non_github_sources_do_not_use_github_noise_terms():
    config = _make_config()
    page = FetchedPage(
        url="https://docs.example.com/docs/start",
        html=(
            "<html><body><main>"
            "<h1>Guide</h1>"
            "<p>" + " ".join(["content"] * 260) + "</p>"
            "<h2>Site-wide Links</h2>"
            "<p>Reference links in the guide</p>"
            "</main></body></html>"
        ),
    )
    parse_result = _parse_document(page, config)
    assert parse_result.document is not None
    assert "Site-wide Links" in parse_result.document.content


def test_host_specific_headers_are_applied():
    config = _make_config(
        extra_headers={
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        }
    )
    headers = _build_client_headers(config)
    assert headers["User-Agent"]
    assert headers["Accept"] == "text/html,application/xhtml+xml"
    assert headers["Accept-Language"] == "en-US,en;q=0.9"


def test_host_specific_blocked_paths_do_not_affect_other_sources():
    cloudflare = _make_config(
        base_url=None,
        start_paths=[],
        urls=["https://blog.cloudflare.com/tag/engineering/"],
        blocked_path_substrings=["/tag/", "/author/"],
    )
    github = _make_config(
        base_url=None,
        start_paths=[],
        urls=["https://github.blog/engineering/"],
        blocked_path_substrings=["/categories/"],
        allowed_path_prefixes=["/engineering/"],
    )
    assert not _is_allowed_url("https://blog.cloudflare.com/tag/rust/", cloudflare)
    assert _is_allowed_url("https://github.blog/engineering/infrastructure/scaling-merge-ort-across-github/", github)
    assert not _is_allowed_url("https://github.blog/tag/rust/", github)


def test_allowed_path_prefixes_constrain_host_specific_crawls():
    uber = _make_config(
        base_url=None,
        start_paths=[],
        urls=["https://www.uber.com/blog/engineering/"],
        allowed_path_prefixes=["/blog/"],
    )
    assert _is_allowed_url("https://www.uber.com/blog/database-federation/", uber)
    assert not _is_allowed_url("https://www.uber.com/us/en/careers/list/", uber)


def test_source_config_combines_start_paths_with_extra_seed_urls():
    config = _make_config(
        start_paths=["/docs/start", "/docs/reference"],
        extra_seed_urls=["https://docs.example.com/docs/critical-page"],
    )
    assert config.seed_urls == [
        "https://docs.example.com/docs/start",
        "https://docs.example.com/docs/reference",
        "https://docs.example.com/docs/critical-page",
    ]


def test_gitlab_source_is_limited_to_eval_focused_paths():
    gitlab = SOURCES["gitlab-handbook"]
    assert "https://handbook.gitlab.com/handbook/engineering/devops/oncall/communication-and-culture/" in gitlab.extra_seed_urls
    assert _is_allowed_url(
        "https://handbook.gitlab.com/handbook/engineering/devops/oncall/communication-and-culture/",
        gitlab,
    )
    assert _is_allowed_url(
        "https://handbook.gitlab.com/handbook/product-development/how-we-work/issue-triage/",
        gitlab,
    )
    assert _is_allowed_url(
        "https://handbook.gitlab.com/handbook/values/",
        gitlab,
    )
    assert not _is_allowed_url(
        "https://handbook.gitlab.com/handbook/hiring/",
        gitlab,
    )
    assert not _is_allowed_url(
        "https://handbook.gitlab.com/handbook/people-group/time-off-and-absence/time-off-types/",
        gitlab,
    )


def test_aws_waf_source_stays_inside_latest_well_architected_paths():
    aws = SOURCES["aws-waf"]
    assert "https://docs.aws.amazon.com/wellarchitected/latest/framework/rel-dp.html" in aws.extra_seed_urls
    assert _is_allowed_url(
        "https://docs.aws.amazon.com/wellarchitected/latest/reliability-pillar/",
        aws,
    )
    assert _is_allowed_url(
        "https://docs.aws.amazon.com/wellarchitected/latest/framework/rel-bp.html",
        aws,
    )
    assert not _is_allowed_url(
        "https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-sso.html",
        aws,
    )
    assert not _is_allowed_url(
        "https://docs.aws.amazon.com/wellarchitected/2024-06-27/framework/welcome.html",
        aws,
    )


def test_netflix_certificate_error_is_classified():
    config = _make_config(
        base_url=None,
        start_paths=[],
        urls=["https://netflixtechblog.com/"],
        tls_fallback_strategy="system_trust_store",
        known_failure_label="environment_blocked_tls",
    )
    exc = httpx.ConnectError(
        "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed",
    )
    assert _classify_fetch_error(exc, config) == (
        "environment_blocked",
        "tls_certificate_verification_failed",
    )


def test_netflix_failure_classification_is_source_local():
    netflix = _make_config(
        base_url=None,
        start_paths=[],
        urls=["https://netflixtechblog.com/"],
        tls_fallback_strategy="system_trust_store",
        known_failure_label="environment_blocked_tls",
    )
    github = _make_config(
        base_url=None,
        start_paths=[],
        urls=["https://github.blog/engineering/"],
        allowed_path_prefixes=["/engineering/"],
    )
    exc = httpx.ConnectError(
        "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed",
    )
    assert _classify_fetch_error(exc, netflix) == (
        "environment_blocked",
        "tls_certificate_verification_failed",
    )
    assert _classify_fetch_error(exc, github) is None


def test_tls_fallback_context_is_source_local():
    netflix = _make_config(
        base_url=None,
        start_paths=[],
        urls=["https://netflixtechblog.com/"],
        tls_fallback_strategy="system_trust_store",
    )
    github = _make_config(
        base_url=None,
        start_paths=[],
        urls=["https://github.blog/engineering/"],
        allowed_path_prefixes=["/engineering/"],
    )
    assert netflix.tls_fallback_strategy == "system_trust_store"
    assert _build_tls_fallback_context(github) is None


def test_github_allowed_path_prefixes_reject_non_engineering_sections():
    github = _make_config(
        key="github-rfcs",
        base_url=None,
        start_paths=[],
        urls=["https://github.blog/engineering/"],
        blocked_path_substrings=["/pricing", "/login", "/account", "/tag/", "/author/", "/categories/"],
        allowed_path_prefixes=["/engineering/"],
    )
    assert not _is_allowed_url("https://github.blog/changelog/2026-03-19-actions-runner-controller-release-0-14-0/", github)
    assert not _is_allowed_url("https://github.blog/developer-skills/github/github-for-beginners-getting-started-with-github-actions/", github)
    assert not _is_allowed_url("https://github.blog/ai-and-ml/github-copilot/how-to-debug-code-with-github-copilot/", github)
    assert not _is_allowed_url("https://github.blog/news-insights/company-news/build-an-agent-into-any-app-with-the-github-copilot-sdk/", github)
    assert not _is_allowed_url("https://github.blog/wp-content/uploads/2025/03/triangular-image-1.png", github)


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


def test_insert_splits_batch_after_repeated_transport_failure(monkeypatch):
    inserted_payload_sizes: list[int] = []
    attempts_by_size: dict[int, int] = {}

    class DummyRequest:
        def __init__(self, payload):
            self.payload = payload

        def execute(self):
            size = len(self.payload)
            attempts_by_size[size] = attempts_by_size.get(size, 0) + 1
            if size > 1:
                raise httpx.ReadError("boom")
            inserted_payload_sizes.append(size)
            return object()

    class DummyTable:
        def insert(self, payload):
            return DummyRequest(payload)

    class DummyClient:
        def table(self, name):
            assert name == "corpus_chunks"
            return DummyTable()

    monkeypatch.setattr("rag.ingest._sleep_backoff", lambda attempt: asyncio.sleep(0))
    monkeypatch.setattr("rag.ingest._get_supabase_client", lambda: DummyClient())
    monkeypatch.setattr("rag.ingest._reset_supabase_client", lambda: DummyClient())

    rows = [
        CorpusChunkRow(
            source_name="Docs",
            source_url=f"https://docs.example.com/{index}",
            section_title="Section",
            content="Body",
            embedding=[0.1, 0.2],
            chunk_index=index,
        )
        for index in range(4)
    ]

    count = asyncio.run(_insert_chunk_rows(DummyClient(), rows))

    assert count == 4
    assert attempts_by_size[4] == 4
    assert attempts_by_size[2] == 8
    assert inserted_payload_sizes == [1, 1, 1, 1]


def test_insert_does_not_split_non_retryable_api_error(monkeypatch):
    attempts_by_size: dict[int, int] = {}

    class DummyRequest:
        def __init__(self, payload):
            self.payload = payload

        def execute(self):
            size = len(self.payload)
            attempts_by_size[size] = attempts_by_size.get(size, 0) + 1
            raise APIError({"status": 400, "message": "bad request"})

    class DummyTable:
        def insert(self, payload):
            return DummyRequest(payload)

    class DummyClient:
        def table(self, name):
            assert name == "corpus_chunks"
            return DummyTable()

    monkeypatch.setattr("rag.ingest._sleep_backoff", lambda attempt: asyncio.sleep(0))
    monkeypatch.setattr("rag.ingest._get_supabase_client", lambda: DummyClient())
    monkeypatch.setattr("rag.ingest._reset_supabase_client", lambda: DummyClient())

    rows = [
        CorpusChunkRow(
            source_name="Docs",
            source_url=f"https://docs.example.com/{index}",
            section_title="Section",
            content="Body",
            embedding=[0.1, 0.2],
            chunk_index=index,
        )
        for index in range(4)
    ]

    try:
        asyncio.run(_insert_chunk_rows(DummyClient(), rows))
    except APIError as exc:
        assert "bad request" in str(exc).lower()
    else:
        raise AssertionError("Expected APIError to be raised")

    assert attempts_by_size == {4: 1}


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


def test_fetch_raises_blocked_source_after_repeated_certificate_error(monkeypatch):
    request = httpx.Request("GET", "https://netflixtechblog.com/")

    class DummyClient:
        def __init__(self):
            self.calls = 0

        async def get(self, url, follow_redirects=True):
            self.calls += 1
            raise httpx.ConnectError(
                "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed",
                request=request,
            )

    monkeypatch.setattr("rag.ingest._sleep_backoff", lambda attempt: asyncio.sleep(0))

    async def run_test():
        client = DummyClient()
        robots = RobotsPolicyCache()
        robots._policies["netflixtechblog.com"] = type(
            "Policy",
            (),
            {"can_fetch": lambda self, user_agent, url: True},
        )()
        config = _make_config(
            base_url=None,
            start_paths=[],
            urls=["https://netflixtechblog.com/"],
            tls_fallback_strategy="system_trust_store",
            known_failure_label="environment_blocked_tls",
        )
        monkeypatch.setattr("rag.ingest._fetch_with_tls_fallback", lambda client, url, config: asyncio.sleep(0, result=None))
        try:
            await _fetch_page(client, "https://netflixtechblog.com/", robots, config)
        except SourceFetchBlocked as exc:
            assert exc.status == "environment_blocked"
            assert exc.detail == "tls_certificate_verification_failed"
        else:
            raise AssertionError("Expected SourceFetchBlocked to be raised")
        assert client.calls == 3

    asyncio.run(run_test())


def test_fetch_uses_tls_fallback_and_succeeds(monkeypatch):
    request = httpx.Request("GET", "https://netflixtechblog.com/")
    response = httpx.Response(
        200,
        request=request,
        headers={"content-type": "text/html"},
        text=(
            "<html><body><main><h1>Netflix Incident Review</h1>"
            "<p>" + " ".join(["content"] * 260) + "</p>"
            "</main></body></html>"
        ),
    )

    class DummyClient:
        def __init__(self):
            self.calls = 0
            self.headers = httpx.Headers({"User-Agent": "test"})
            self.timeout = httpx.Timeout(20.0, connect=10.0)

        async def get(self, url, follow_redirects=True):
            self.calls += 1
            raise httpx.ConnectError(
                "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed",
                request=request,
            )

    async def fallback_fetch(client, url, config):
        return response

    monkeypatch.setattr("rag.ingest._sleep_backoff", lambda attempt: asyncio.sleep(0))
    monkeypatch.setattr("rag.ingest._fetch_with_tls_fallback", fallback_fetch)

    async def run_test():
        client = DummyClient()
        robots = RobotsPolicyCache()
        robots._policies["netflixtechblog.com"] = type(
            "Policy",
            (),
            {"can_fetch": lambda self, user_agent, url: True},
        )()
        config = _make_config(
            base_url=None,
            start_paths=[],
            urls=["https://netflixtechblog.com/"],
            tls_fallback_strategy="system_trust_store",
            known_failure_label="environment_blocked_tls",
        )
        page = await _fetch_page(client, "https://netflixtechblog.com/", robots, config)
        assert page is not None
        parse_result = _parse_document(page, config)
        assert parse_result.document is not None
        assert parse_result.document.section_title == "Netflix Incident Review"

    asyncio.run(run_test())
