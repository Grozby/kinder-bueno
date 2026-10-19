import asyncio

import httpx

from navigator.crawl import LinkFilter, crawl_source
from navigator.settings import BACKEND_ROOT
from navigator.sources import CrawlDefaults, SourceConfig, load_sources

SOURCES = load_sources(BACKEND_ROOT / "config" / "sources.yaml")
FAST = CrawlDefaults(delay_seconds=0, max_depth=3)
FILLER = "Research on continuous glucose monitoring and biosensing. " * 3


def test_artorg_filter():
    f = LinkFilter(SOURCES.get("artorg"))
    assert f.accepts("https://www.artorg.unibe.ch/research/msl/group_members/index_eng.html")
    assert not f.accepts("https://www.artorg.unibe.ch/research/msl/index_ger.html")  # German duplicate
    assert not f.accepts("https://www.artorg.unibe.ch/news_and_events/index_eng.html")
    assert not f.accepts("https://www.unibe.ch/index_eng.html")  # other host
    assert f.is_priority("https://www.artorg.unibe.ch/research/igt/index_eng.html")
    assert f.is_priority("https://www.artorg.unibe.ch/research/igt/group_members/index_eng.html")
    # Individual project pages are allowed, but they must not eat the budget before member lists.
    assert not f.is_priority("https://www.artorg.unibe.ch/research/aimi/research/oct/index_eng.html")


def test_unibe_filter_stays_on_biomedical_hosts():
    f = LinkFilter(SOURCES.get("unibe"))
    assert f.accepts("https://www.dbmr.unibe.ch/research/research_programs/odening_lab/index_eng.html")
    assert f.is_priority("https://www.dbmr.unibe.ch/research/research_programs/odening_lab/index_eng.html")
    assert not f.accepts("https://www.artorg.unibe.ch/research/index_eng.html")  # own source
    assert not f.accepts("https://www.upz.unibe.ch/research/index_eng.html")  # psychiatry, off-topic
    assert not f.accepts("https://www.dbmr.unibe.ch/research/dbmr_travel_awards/index_eng.html")


def test_deny_hosts_and_host_regex():
    source = SourceConfig(
        id="x", name="X", seeds=["https://www.unibe.ch/"], allow_hosts_regex=r"^[a-z0-9.-]+\.unibe\.ch$",
        deny_hosts=["karriere.unibe.ch"], max_pages=1,
    )
    f = LinkFilter(source)
    assert f.accepts("https://www.dbmr.unibe.ch/x")
    assert not f.accepts("https://karriere.unibe.ch/x")
    assert not f.accepts("https://www.unibe.ch.evil.com/x")


def test_dcb_filter_keeps_english_only():
    f = LinkFilter(SOURCES.get("dcb"))
    assert f.accepts("https://www.dcberne.com/en/team/")
    assert not f.accepts("https://www.dcberne.com/de/team/")
    assert not f.accepts("https://www.dcberne.com/en/wp-json/wp/v2/pages/96")
    assert not f.accepts("https://www.dcberne.com/en/?s=glucose")
    assert not f.accepts("https://www.dcberne.com/en/category/reserach/page/2/")  # news listing
    assert f.is_priority("https://www.dcberne.com/en/project/insulin-activity-project/")


def _site(pages: dict[str, str], robots: str = "", log: list | None = None) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if log is not None:
            log.append(url)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=robots)
        if url in pages:
            return httpx.Response(200, html=pages[url])
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def _page(body: str) -> str:
    return f"<html><head><title>T</title></head><body><main><p>{FILLER}</p>{body}</main></body></html>"


TEST_SOURCE = SourceConfig(
    id="test",
    name="Test",
    seeds=["https://lab.test/"],
    allow_hosts=["lab.test"],
    exclude_patterns=["/news/"],
    priority_patterns=["/team/"],
    max_pages=10,
)


def test_crawl_follows_links_and_respects_rules():
    site = {
        "https://lab.test/": _page('<a href="/a">A</a><a href="/team/">Team</a><a href="/news/1">N</a>'
                                   '<a href="https://other.test/">X</a><a href="/secret/">S</a>'),
        "https://lab.test/a": _page('<a href="/">home</a>'),
        "https://lab.test/team/": _page("<p>Dr. Jane Doe</p>"),
        "https://lab.test/news/1": _page(""),
        "https://lab.test/secret/": _page(""),
    }
    fetched: list[str] = []
    pages = asyncio.run(
        crawl_source(TEST_SOURCE, FAST, transport=_site(site, "User-agent: *\nDisallow: /secret/", fetched))
    )
    urls = [p.url for p in pages]
    assert urls == ["https://lab.test/", "https://lab.test/team/", "https://lab.test/a"]  # priority first
    assert "https://lab.test/news/1" not in fetched  # excluded
    assert "https://lab.test/secret/" not in fetched  # robots.txt
    assert not any("other.test" in u for u in fetched)  # other host


def test_crawl_stops_at_max_pages_and_skips_duplicates_and_short_pages():
    links = "".join(f'<a href="/p{i}">p</a>' for i in range(10))
    site = {"https://lab.test/": _page(links)}
    site |= {f"https://lab.test/p{i}": _page(f"<p>page {i}</p>") for i in range(10)}
    site["https://lab.test/p0"] = site["https://lab.test/"]  # same text as home → duplicate
    site["https://lab.test/p1"] = "<html><body><main>tiny</main></body></html>"  # too short
    pages = asyncio.run(crawl_source(TEST_SOURCE, FAST, max_pages=4, transport=_site(site)))
    assert [p.url for p in pages] == [
        "https://lab.test/", "https://lab.test/p2", "https://lab.test/p3", "https://lab.test/p4",
    ]


def test_crawl_survives_errors_and_non_html():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            raise httpx.ConnectError("down")
        if request.url.path == "/broken":
            raise httpx.ReadTimeout("slow")
        if request.url.path == "/file.pdf":
            return httpx.Response(200, content=b"%PDF", headers={"content-type": "application/pdf"})
        return httpx.Response(200, html=_page('<a href="/broken">b</a><a href="/file.pdf">f</a>'))

    pages = asyncio.run(crawl_source(TEST_SOURCE, FAST, transport=httpx.MockTransport(handler)))
    assert [p.url for p in pages] == ["https://lab.test/"]


def test_crawl_reports_every_url_with_parent_depth_and_status():
    site = {
        "https://lab.test/": _page('<a href="/a">A</a><a href="/team/">Team</a><a href="/secret/">S</a>'
                                   '<a href="/gone">G</a>'),
        "https://lab.test/a": _page('<a href="/short">short</a>'),
        "https://lab.test/team/": _page(""),
        "https://lab.test/short": "<html><body>tiny</body></html>",
    }
    events: list[tuple] = []
    asyncio.run(crawl_source(TEST_SOURCE, FAST, transport=_site(site, "User-agent: *\nDisallow: /secret/"),
                             on_url=lambda *e: events.append(e)))
    final = {url: (parent, depth, status) for url, parent, depth, status in events}
    assert events[0] == ("https://lab.test/", None, 0, "queued")
    assert final == {
        "https://lab.test/": (None, 0, "crawled"),
        "https://lab.test/team/": ("https://lab.test/", 1, "crawled"),
        "https://lab.test/a": ("https://lab.test/", 1, "crawled"),
        "https://lab.test/secret/": ("https://lab.test/", 1, "skipped"),  # robots.txt
        "https://lab.test/gone": ("https://lab.test/", 1, "failed"),  # 404
        "https://lab.test/short": ("https://lab.test/a", 2, "skipped"),  # too little text
    }
