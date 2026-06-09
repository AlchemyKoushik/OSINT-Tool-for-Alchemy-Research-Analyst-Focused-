from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from config.settings import settings
from services.crawlers.base import BaseCrawler, CrawlResultPayload

logger = logging.getLogger(__name__)

try:
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig
    from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator

    CRAWL4AI_IMPORT_ERROR = ""
except Exception as exc:
    AsyncWebCrawler = None  # type: ignore[assignment]
    BrowserConfig = None  # type: ignore[assignment]
    CacheMode = None  # type: ignore[assignment]
    CrawlerRunConfig = None  # type: ignore[assignment]
    DefaultMarkdownGenerator = None  # type: ignore[assignment]
    CRAWL4AI_IMPORT_ERROR = str(exc)


def _extract_markdown_strings(markdown: Any) -> tuple[str, str, str]:
    if markdown is None:
        return "", "", ""
    if isinstance(markdown, str):
        return markdown, markdown, markdown
    raw_markdown = str(getattr(markdown, "raw_markdown", "") or "")
    fit_markdown = str(getattr(markdown, "fit_markdown", "") or "")
    markdown_with_citations = str(getattr(markdown, "markdown_with_citations", "") or "")
    primary = fit_markdown or raw_markdown or markdown_with_citations
    return primary, raw_markdown or primary, fit_markdown or primary


class Crawl4AICrawler(BaseCrawler):
    crawler_name = "crawl4ai"

    def __init__(self) -> None:
        self._crawler: Any | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        if AsyncWebCrawler is None:
            raise RuntimeError(f"Crawl4AI is unavailable: {CRAWL4AI_IMPORT_ERROR or 'import failed'}")
        if self._crawler is not None:
            return
        async with self._lock:
            if self._crawler is not None:
                return
            browser_config = BrowserConfig(
                browser_type="chromium",
                headless=True,
                verbose=False,
            )
            crawler = AsyncWebCrawler(config=browser_config)
            await crawler.start()
            self._crawler = crawler
            logger.info("Crawl4AI crawler started")

    async def close(self) -> None:
        crawler = self._crawler
        self._crawler = None
        if crawler is None:
            return
        try:
            await crawler.close()
        except Exception:
            logger.warning("Failed to close Crawl4AI crawler cleanly", exc_info=True)

    async def crawl(self, url: str) -> CrawlResultPayload:
        started_at = time.perf_counter()
        try:
            await self.start()
        except Exception as exc:
            return self.build_failure(url, str(exc), started_at=started_at)

        try:
            assert self._crawler is not None
            run_config = CrawlerRunConfig(
                cache_mode=CacheMode.BYPASS if CacheMode is not None else None,
                page_timeout=max(5000, int(settings.CRAWL4AI_TIMEOUT_SECONDS * 1000)),
                markdown_generator=DefaultMarkdownGenerator(
                    options={
                        "ignore_links": False,
                        "body_width": 0,
                    }
                ),
                remove_overlay_elements=True,
                simulate_user=True,
                scan_full_page=True,
                wait_until="domcontentloaded",
            )
            result = await self._crawler.arun(url=url, config=run_config)
            markdown, raw_markdown, clean_markdown = _extract_markdown_strings(getattr(result, "markdown", None))
            metadata = dict(getattr(result, "metadata", None) or {})
            media = getattr(result, "media", None) or {}
            image_url = ""
            if isinstance(media, dict):
                images = media.get("images", []) or []
                if images:
                    first_image = images[0]
                    if isinstance(first_image, dict):
                        image_url = str(first_image.get("src", "")).strip()

            payload = CrawlResultPayload(
                url=str(getattr(result, "url", url) or url),
                title=str(metadata.get("title") or getattr(result, "title", "") or ""),
                markdown=markdown,
                raw_markdown=raw_markdown,
                clean_markdown=clean_markdown,
                plain_text=clean_markdown or raw_markdown or markdown,
                structured_content=str(getattr(result, "extracted_content", "") or ""),
                metadata=metadata,
                crawler_used=self.crawler_name,
                crawl_duration_ms=int((time.perf_counter() - started_at) * 1000),
                image_url=image_url,
                error="" if bool(getattr(result, "success", False)) else str(getattr(result, "error_message", "") or "Crawl4AI crawl failed."),
                status_code=getattr(result, "status_code", None),
            ).ensure_metrics()
            if not payload.title:
                payload.title = str(metadata.get("og:title") or metadata.get("title") or "")
            return payload
        except Exception as exc:
            return self.build_failure(url, str(exc), started_at=started_at)


_shared_crawler: Crawl4AICrawler | None = None
_shared_lock = asyncio.Lock()


async def get_shared_crawl4ai_crawler() -> Crawl4AICrawler:
    global _shared_crawler
    if _shared_crawler is not None:
        return _shared_crawler
    async with _shared_lock:
        if _shared_crawler is None:
            crawler = Crawl4AICrawler()
            await crawler.start()
            _shared_crawler = crawler
    assert _shared_crawler is not None
    return _shared_crawler
