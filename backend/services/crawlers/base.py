from __future__ import annotations

import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List

BOILERPLATE_MARKERS = (
    "cookie policy",
    "privacy policy",
    "all rights reserved",
    "subscribe",
    "sign in",
    "newsletter",
    "advertisement",
    "accept cookies",
)
MEANINGFUL_PARAGRAPH_PATTERN = re.compile(r"(?s)(.+?)(?:\n\s*\n|$)")
ENTITY_PATTERN = re.compile(r"\b(?:[A-Z][a-z]+(?:\s+[A-Z][A-Za-z0-9&.-]+){0,3})\b")


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def count_meaningful_paragraphs(text: str) -> int:
    count = 0
    for match in MEANINGFUL_PARAGRAPH_PATTERN.finditer(str(text or "")):
        paragraph = normalize_whitespace(match.group(1))
        if len(paragraph) >= 80 and len(paragraph.split()) >= 12:
            count += 1
    return count


def boilerplate_ratio(text: str) -> float:
    normalized = normalize_whitespace(text).lower()
    if not normalized:
        return 1.0
    hits = sum(1 for marker in BOILERPLATE_MARKERS if marker in normalized)
    return min(1.0, hits / max(1, len(BOILERPLATE_MARKERS) // 2))


def extraction_quality_score(markdown: str, plain_text: str) -> float:
    normalized_text = normalize_whitespace(plain_text)
    normalized_markdown = normalize_whitespace(markdown)
    content_score = min(1.0, len(normalized_text) / 2400.0)
    markdown_score = min(1.0, len(normalized_markdown) / 2200.0)
    paragraph_score = min(1.0, count_meaningful_paragraphs(markdown or plain_text) / 6.0)
    boilerplate_penalty = boilerplate_ratio(plain_text)
    score = (content_score * 0.45) + (markdown_score * 0.25) + (paragraph_score * 0.30)
    return max(0.0, min(1.0, score - (boilerplate_penalty * 0.25)))


def estimate_entity_coverage(text: str) -> int:
    entities = {normalize_whitespace(match.group(0)) for match in ENTITY_PATTERN.finditer(str(text or ""))}
    return len({entity for entity in entities if len(entity) >= 4})


@dataclass
class CrawlResultPayload:
    url: str
    title: str = ""
    markdown: str = ""
    raw_markdown: str = ""
    clean_markdown: str = ""
    plain_text: str = ""
    structured_content: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    crawler_used: str = ""
    crawl_duration_ms: int = 0
    content_length: int = 0
    markdown_length: int = 0
    fallback_triggered: bool = False
    extraction_quality_score: float = 0.0
    image_url: str = ""
    error: str = ""
    status_code: int | None = None

    def ensure_metrics(self) -> "CrawlResultPayload":
        self.markdown = str(self.markdown or "")
        self.raw_markdown = str(self.raw_markdown or self.markdown or "")
        self.clean_markdown = str(self.clean_markdown or self.markdown or "")
        self.plain_text = normalize_whitespace(self.plain_text or self.clean_markdown or self.raw_markdown)
        self.content_length = len(self.plain_text)
        self.markdown_length = len(normalize_whitespace(self.clean_markdown or self.raw_markdown))
        if self.extraction_quality_score <= 0:
            self.extraction_quality_score = extraction_quality_score(self.clean_markdown, self.plain_text)
        return self

    @property
    def is_success(self) -> bool:
        return not self.error and self.content_length > 0


class BaseCrawler(ABC):
    crawler_name = "base"

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def __aenter__(self) -> "BaseCrawler":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    @abstractmethod
    async def crawl(self, url: str) -> CrawlResultPayload:
        raise NotImplementedError

    def build_failure(self, url: str, error: str, *, started_at: float | None = None) -> CrawlResultPayload:
        duration_ms = int((time.perf_counter() - started_at) * 1000) if started_at is not None else 0
        return CrawlResultPayload(
            url=url,
            crawler_used=self.crawler_name,
            crawl_duration_ms=duration_ms,
            error=error,
        ).ensure_metrics()


def crawler_result_to_dict(payload: CrawlResultPayload) -> Dict[str, Any]:
    return {
        "url": payload.url,
        "title": payload.title,
        "markdown": payload.markdown,
        "raw_markdown": payload.raw_markdown,
        "clean_markdown": payload.clean_markdown,
        "plain_text": payload.plain_text,
        "structured_content": payload.structured_content,
        "metadata": dict(payload.metadata),
        "crawler_used": payload.crawler_used,
        "crawl_duration_ms": int(payload.crawl_duration_ms),
        "content_length": int(payload.content_length),
        "markdown_length": int(payload.markdown_length),
        "fallback_triggered": bool(payload.fallback_triggered),
        "extraction_quality_score": float(payload.extraction_quality_score),
        "image_url": payload.image_url,
        "error": payload.error,
        "status_code": payload.status_code,
    }
