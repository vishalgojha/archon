"""Async site crawling utilities for ARCHON web analysis."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Iterable
from urllib.parse import urldefrag, urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import httpx

ARCHON_CRAWLER_USER_AGENT = "ARCHON-Crawler/1.0 (+https://archon.local/crawler)"

_BINARY_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".webp",
        ".svg",
        ".ico",
        ".pdf",
        ".zip",
        ".gz",
        ".tar",
        ".rar",
        ".7z",
        ".mp4",
        ".mov",
        ".avi",
        ".mp3",
        ".wav",
        ".woff",
        ".woff2",
        ".ttf",
        ".otf",
        ".exe",
        ".dmg",
    }
)

@dataclass(slots=True, frozen=True)
class PageData:
    """Normalized page extraction payload."""

    url: str
    title: str
    text_content: str
    meta_description: str
    h1s: list[str]
    links: list[str]
    load_ms: float


@dataclass(slots=True)
class CrawlResult:
    """Site crawl output."""

    pages: list[PageData] = field(default_factory=list)


class SiteCrawler:
    """Asynchronous domain-scoped crawler with robots.txt support."""

    def __init__(
        self,
        *,
        max_concurrent: int = 5,
        delay_between_requests_ms: int = 200,
        timeout_seconds: float = 15.0,
    ) -> None:
        self.max_concurrent = max(1, int(max_concurrent))
        self.delay_between_requests_ms = max(0, int(delay_between_requests_ms))
        self._request_delay_seconds = self.delay_between_requests_ms / 1000.0
        self._client = httpx.AsyncClient(
            timeout=timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": ARCHON_CRAWLER_USER_AGENT},
        )
        self._semaphore = asyncio.Semaphore(self.max_concurrent)
        self._delay_lock = asyncio.Lock()
        self._last_request_ts = 0.0
        self._robots_cache: dict[str, RobotFileParser] = {}

    async def aclose(self) -> None:
        """Close network resources used by the crawler."""

        await self._client.aclose()

    async def crawl(self, url: str, max_pages: int = 50, max_depth: int = 3) -> CrawlResult:
        """Crawl one domain up to depth/page limits.

        Example:
            >>> result = await crawler.crawl("https://example.com", max_pages=10, max_depth=2)
            >>> isinstance(result.pages, list)
            True
        """

        max_pages = max(1, int(max_pages))
        max_depth = max(0, int(max_depth))
        start_url = _normalize_url(url)
        start_netloc = _canonical_netloc(start_url)
        queue: deque[tuple[str, int]] = deque([(start_url, 0)])
        discovered: set[str] = {start_url}
        pages: list[PageData] = []

        while queue and len(pages) < max_pages:
            batch: list[tuple[str, int]] = []
            while queue and len(batch) < self.max_concurrent and len(batch) + len(pages) < max_pages:
                batch.append(queue.popleft())
            if not batch:
                break

            tasks = [self._crawl_fetch_one(current_url, current_depth) for current_url, current_depth in batch]
            fetched = await asyncio.gather(*tasks)

            for current_url, current_depth, page in fetched:
                if page is None:
                    continue
                pages.append(page)
                if current_depth >= max_depth or len(discovered) >= max_pages:
                    continue

                for link in page.links:
                    normalized = _normalize_url(link, base=current_url)
                    if normalized in discovered:
                        continue
                    if _canonical_netloc(normalized) != start_netloc:
                        continue
                    if _is_binary_or_media_url(normalized):
                        continue
                    discovered.add(normalized)
                    queue.append((normalized, current_depth + 1))
                    if len(discovered) >= max_pages:
                        break

        return CrawlResult(pages=pages)

    async def crawl_single(self, url: str) -> PageData:
        """Fetch and parse one URL without multi-page traversal."""

        normalized_url = _normalize_url(url)
        page = await self._fetch_page(normalized_url)
        if page is None:
            raise RuntimeError(f"Failed to crawl URL: {normalized_url}")
        return page

    async def _crawl_fetch_one(self, url: str, depth: int) -> tuple[str, int, PageData | None]:
        if not await self._allowed_by_robots(url):
            return url, depth, None
        page = await self._fetch_page(url)
        return url, depth, page

    async def _fetch_page(self, url: str) -> PageData | None:
        if _is_binary_or_media_url(url):
            return None
        await self._wait_for_rate_limit()

        start = time.perf_counter()
        try:
            async with self._semaphore:
                response = await self._client.get(url)
        except Exception:
            return None
        load_ms = (time.perf_counter() - start) * 1000

        if response.status_code >= 400:
            return None
        content_type = (response.headers.get("content-type") or "").lower()
        if "text/html" not in content_type and "application/xhtml+xml" not in content_type:
            return None

        parser = _SimpleHTMLParser()
        parser.feed(response.text)
        parser.close()
        links = [_normalize_url(href, base=str(response.url)) for href in parser.links]
        return PageData(
            url=str(response.url),
            title=parser.title.strip(),
            text_content=parser.text_content.strip(),
            meta_description=parser.meta_description.strip(),
            h1s=[value.strip() for value in parser.h1s if value.strip()],
            links=list(dict.fromkeys(links)),
            load_ms=round(load_ms, 3),
        )

    async def _allowed_by_robots(self, url: str) -> bool:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        parser = self._robots_cache.get(origin)
        if parser is None:
            robots_url = f"{origin}/robots.txt"
            parser = RobotFileParser()
            parser.set_url(robots_url)
            try:
                await self._wait_for_rate_limit()
                async with self._semaphore:
                    response = await self._client.get(robots_url)
                if response.status_code < 400:
                    parser.parse(response.text.splitlines())
                else:
                    parser.parse([])
            except Exception:
                parser.parse([])
            self._robots_cache[origin] = parser
        return parser.can_fetch(ARCHON_CRAWLER_USER_AGENT, url)

    async def _wait_for_rate_limit(self) -> None:
        if self._request_delay_seconds <= 0:
            return
        async with self._delay_lock:
            now = time.perf_counter()
            wait_for = self._request_delay_seconds - (now - self._last_request_ts)
            if wait_for > 0:
                await asyncio.sleep(wait_for)
            self._last_request_ts = time.perf_counter()


class _SimpleHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.meta_description = ""
        self.h1s: list[str] = []
        self.links: list[str] = []
        self._text_chunks: list[str] = []
        self._tag_stack: list[str] = []
        self._capture_h1 = False
        self._current_h1: list[str] = []

    @property
    def text_content(self) -> str:
        cleaned = " ".join(self._text_chunks)
        return " ".join(cleaned.split())

    def handle_starttag(self, tag: str, attrs: Iterable[tuple[str, str | None]]) -> None:
        lower = tag.lower()
        self._tag_stack.append(lower)
        attrs_map = {key.lower(): value or "" for key, value in attrs}
        if lower == "a":
            href = attrs_map.get("href", "")
            if href:
                self.links.append(href)
        elif lower == "meta" and attrs_map.get("name", "").lower() == "description":
            if not self.meta_description:
                self.meta_description = attrs_map.get("content", "")
        elif lower == "h1":
            self._capture_h1 = True
            self._current_h1 = []

    def handle_endtag(self, tag: str) -> None:
        lower = tag.lower()
        if self._tag_stack:
            self._tag_stack.pop()
        if lower == "h1":
            self._capture_h1 = False
            text = " ".join(self._current_h1).strip()
            if text:
                self.h1s.append(text)
            self._current_h1 = []

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if not text:
            return
        current_tag = self._tag_stack[-1] if self._tag_stack else ""
        if current_tag in {"script", "style", "noscript"}:
            return
        if current_tag == "title":
            self.title = (self.title + " " + text).strip()
        if self._capture_h1:
            self._current_h1.append(text)
        self._text_chunks.append(text)


def _normalize_url(url: str, *, base: str | None = None) -> str:
    joined = urljoin(base, url) if base else url
    joined, _fragment = urldefrag(joined.strip())
    parsed = urlparse(joined)
    scheme = parsed.scheme.lower() or "https"
    netloc = parsed.netloc.lower()
    path = parsed.path or "/"
    normalized = parsed._replace(scheme=scheme, netloc=netloc, path=path)
    return urlunparse(normalized)


def _canonical_netloc(url: str) -> str:
    parsed = urlparse(url)
    return parsed.netloc.lower()


def _is_binary_or_media_url(url: str) -> bool:
    path = urlparse(url).path.lower()
    return any(path.endswith(extension) for extension in _BINARY_EXTENSIONS)
