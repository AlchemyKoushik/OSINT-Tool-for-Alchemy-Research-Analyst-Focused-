from __future__ import annotations

import asyncio
import logging
import time
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from playwright.async_api import Browser, Page, async_playwright

from config.settings import settings
from services.crawlers.base import BaseCrawler, CrawlResultPayload, normalize_whitespace

logger = logging.getLogger(__name__)


def _html_to_markdown(html: str) -> str:
    if not html.strip():
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "aside", "form", "svg"]):
        tag.extract()

    segments = []
    root = soup.find("main") or soup.find("article") or soup.find("body") or soup
    for element in root.find_all(["h1", "h2", "h3", "h4", "p", "li"]):
        text = normalize_whitespace(element.get_text(" ", strip=True))
        if len(text) < 30:
            continue
        prefix = ""
        if element.name == "li":
            prefix = "- "
        elif element.name in {"h1", "h2", "h3", "h4"}:
            prefix = "#" * int(element.name[1]) + " "
        segments.append(f"{prefix}{text}".strip())
    return "\n\n".join(segments).strip()


def _extract_image_url(html: str, page_url: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for attrs in (
        {"property": "og:image"},
        {"name": "og:image"},
        {"property": "twitter:image"},
        {"name": "twitter:image"},
    ):
        meta_tag = soup.find("meta", attrs=attrs)
        if meta_tag and meta_tag.get("content"):
            return urljoin(page_url, str(meta_tag.get("content")).strip())
    return ""


class PlaywrightFallbackCrawler(BaseCrawler):
    crawler_name = "playwright"

    def __init__(self) -> None:
        self._playwright = None
        self._browser: Browser | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        if self._browser is not None:
            return
        async with self._lock:
            if self._browser is not None:
                return
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=True)
            logger.info("Playwright fallback crawler started")

    async def close(self) -> None:
        browser = self._browser
        playwright_instance = self._playwright
        self._browser = None
        self._playwright = None
        if browser is not None:
            await browser.close()
        if playwright_instance is not None:
            await playwright_instance.stop()

    async def crawl(self, url: str) -> CrawlResultPayload:
        started_at = time.perf_counter()
        try:
            await self.start()
            assert self._browser is not None
            page: Page = await self._browser.new_page()
            try:
                response = await page.goto(url, wait_until="networkidle", timeout=settings.CRAWL4AI_TIMEOUT_SECONDS * 1000)
                await page.wait_for_timeout(1200)
                html = await page.content()
                title = await page.title()
                markdown = _html_to_markdown(html)
                image_url = _extract_image_url(html, url)
                metadata = {
                    "title": title,
                    "status": response.status if response is not None else None,
                }
                return CrawlResultPayload(
                    url=url,
                    title=title,
                    markdown=markdown,
                    raw_markdown=markdown,
                    clean_markdown=markdown,
                    plain_text=markdown,
                    metadata=metadata,
                    crawler_used=self.crawler_name,
                    crawl_duration_ms=int((time.perf_counter() - started_at) * 1000),
                    image_url=image_url,
                    status_code=response.status if response is not None else None,
                ).ensure_metrics()
            finally:
                await page.close()
        except Exception as exc:
            return self.build_failure(url, str(exc), started_at=started_at)


_shared_crawler: PlaywrightFallbackCrawler | None = None
_shared_lock = asyncio.Lock()


async def get_shared_playwright_fallback_crawler() -> PlaywrightFallbackCrawler:
    global _shared_crawler
    if _shared_crawler is not None:
        return _shared_crawler
    async with _shared_lock:
        if _shared_crawler is None:
            crawler = PlaywrightFallbackCrawler()
            await crawler.start()
            _shared_crawler = crawler
    assert _shared_crawler is not None
    return _shared_crawler
