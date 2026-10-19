"""Polite breadth-first crawler: one source at a time, robots.txt, per-host delay, page cap."""

import asyncio
import hashlib
import logging
import re
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from navigator.clean import clean_html
from navigator.sources import CrawlDefaults, SourceConfig

log = logging.getLogger(__name__)

MIN_TEXT_CHARS = 100  # pages with less text are only used for their links

# Called for every URL the crawler meets: (url, parent, depth, status). Status is "queued" when the URL
# is queued, then "crawled" (stored), "skipped" (robots.txt, not HTML, too little text, duplicate) or
# "failed" (network error, non-200). It draws the live crawl graph (FRONTEND_API "Sources", #55).
OnUrl = Callable[[str, str | None, int, str], None]


@dataclass
class CrawledPage:
    url: str
    title: str
    text: str


class LinkFilter:
    """Decides which URLs belong to a source, in the order: host → include → exclude."""

    def __init__(self, source: SourceConfig):
        self.allow_hosts = {h.lower() for h in source.allow_hosts}
        self.allow_hosts_re = re.compile(source.allow_hosts_regex) if source.allow_hosts_regex else None
        self.deny_hosts = {h.lower() for h in source.deny_hosts}
        self.include = [re.compile(p) for p in source.include_patterns]
        self.exclude = [re.compile(p) for p in source.exclude_patterns]
        self.priority = [re.compile(p) for p in source.priority_patterns]

    def host_allowed(self, host: str) -> bool:
        host = host.lower()
        if host in self.deny_hosts:
            return False
        return host in self.allow_hosts or bool(self.allow_hosts_re and self.allow_hosts_re.match(host))

    def accepts(self, url: str) -> bool:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not self.host_allowed(parts.hostname or ""):
            return False
        if self.include and not any(p.search(url) for p in self.include):
            return False
        return not any(p.search(url) for p in self.exclude)

    def is_priority(self, url: str) -> bool:
        return any(p.search(url) for p in self.priority)


class RobotsCache:
    def __init__(self, client: httpx.AsyncClient, user_agent: str):
        self.client = client
        self.user_agent = user_agent
        self.parsers: dict[str, RobotFileParser] = {}

    async def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self.parsers:
            parser = RobotFileParser()
            try:
                resp = await self.client.get(f"{origin}/robots.txt")
                parser.parse(resp.text.splitlines() if resp.status_code == 200 else [])
            except httpx.HTTPError:
                parser.parse([])  # no robots.txt reachable → allow
            self.parsers[origin] = parser
        return self.parsers[origin].can_fetch(self.user_agent, url)


class HostThrottle:
    def __init__(self, delay_seconds: float):
        self.delay = delay_seconds
        self.last: dict[str, float] = {}

    async def wait(self, url: str) -> None:
        host = urlsplit(url).netloc
        elapsed = time.monotonic() - self.last.get(host, 0.0)
        if elapsed < self.delay:
            await asyncio.sleep(self.delay - elapsed)
        self.last[host] = time.monotonic()


async def crawl_source(
    source: SourceConfig,
    defaults: CrawlDefaults,
    max_pages: int | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    on_url: OnUrl | None = None,
) -> list[CrawledPage]:
    """Crawl one source. Seeds are always fetched; other URLs must pass the source's LinkFilter."""
    limit = max_pages or source.max_pages
    link_filter = LinkFilter(source)
    throttle = HostThrottle(defaults.delay_seconds)
    report = on_url or (lambda url, parent, depth, status: None)

    seeds = list(dict.fromkeys(source.seeds))
    priority: deque[tuple[str, int, str | None]] = deque((url, 0, None) for url in seeds)
    normal: deque[tuple[str, int, str | None]] = deque()
    for url in seeds:
        report(url, None, 0, "queued")
    seen: set[str] = set(seeds)
    text_hashes: set[str] = set()
    pages: list[CrawledPage] = []

    async with httpx.AsyncClient(
        headers={"User-Agent": defaults.user_agent},
        timeout=defaults.timeout_seconds,
        follow_redirects=True,
        transport=transport,
    ) as client:
        robots = RobotsCache(client, defaults.user_agent)

        while len(pages) < limit and (priority or normal):
            url, depth, parent = (priority or normal).popleft()
            if not await robots.allowed(url):
                log.info("[%s] robots.txt disallows %s", source.id, url)
                report(url, parent, depth, "skipped")
                continue

            await throttle.wait(url)
            try:
                resp = await client.get(url)
            except httpx.HTTPError as e:
                log.warning("[%s] fetch failed %s: %s", source.id, url, e)
                report(url, parent, depth, "failed")
                continue
            log.info("[%s] %s %s", source.id, resp.status_code, url)

            final_url = str(resp.url)
            if final_url != url:
                if final_url in seen or (url not in seeds and not link_filter.accepts(final_url)):
                    report(url, parent, depth, "skipped")
                    continue
                seen.add(final_url)
            if resp.status_code != 200:
                report(url, parent, depth, "failed")
                continue
            if "text/html" not in resp.headers.get("content-type", ""):
                report(url, parent, depth, "skipped")
                continue

            page = clean_html(resp.text, final_url)
            digest = hashlib.sha256(page.text.encode()).hexdigest()
            if len(page.text) >= MIN_TEXT_CHARS and digest not in text_hashes:
                text_hashes.add(digest)
                pages.append(CrawledPage(url=final_url, title=page.title, text=page.text))
                report(url, parent, depth, "crawled")
            else:
                report(url, parent, depth, "skipped")

            if depth >= defaults.max_depth:
                continue
            for link in page.links:
                if link not in seen and link_filter.accepts(link):
                    seen.add(link)
                    (priority if link_filter.is_priority(link) else normal).append((link, depth + 1, url))
                    report(link, url, depth + 1, "queued")

    log.info("[%s] stored %d pages", source.id, len(pages))
    return pages
