from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Awaitable, Callable, Dict

from config.settings import settings
from core.diagnostics import get_system_health_snapshot

logger = logging.getLogger(__name__)


def format_duration_seconds(value: float) -> str:
    seconds = max(float(value), 0.0)
    if seconds >= 60:
        minutes = int(seconds // 60)
        remaining_seconds = seconds - (minutes * 60)
        return f"{minutes}m {remaining_seconds:.1f}s"
    return f"{seconds:.2f}s"


def log_cl_perf(stage: str, elapsed_seconds: float, **details: Any) -> None:
    detail_parts = [f"{key}={details[key]}" for key in sorted(details) if details[key] not in (None, "", [], {})]
    suffix = f" | {' '.join(detail_parts)}" if detail_parts else ""
    logger.info("[CL PERF] %s: %s%s", stage, format_duration_seconds(elapsed_seconds), suffix)


def log_cl_health(stage: str, **details: Any) -> None:
    snapshot = get_system_health_snapshot()
    merged_details = {
        **details,
        "cpu_percent": snapshot.get("process_cpu_percent", 0.0),
        "process_memory_mb": snapshot.get("process_memory_mb", 0.0),
        "system_memory_percent": snapshot.get("memory_percent", 0.0),
    }
    log_cl_perf(stage, 0.0, **merged_details)


def resolve_cl_enrichment_concurrency() -> int:
    configured = int(settings.CL_ENRICHMENT_CONCURRENCY or 0)
    if configured > 0:
        return configured
    cpu_count = max(1, os.cpu_count() or 1)
    return max(2, min(4, cpu_count))


def resolve_cl_discovery_concurrency() -> int:
    configured = int(settings.CL_DISCOVERY_CONCURRENCY or 0)
    if configured > 0:
        return configured
    cpu_count = max(1, os.cpu_count() or 1)
    return max(2, min(4, cpu_count))


class _ProviderGate:
    def __init__(self, *, concurrency: int, min_interval_ms: int) -> None:
        self._semaphore = asyncio.Semaphore(max(1, int(concurrency)))
        self._min_interval_seconds = max(0.0, float(min_interval_ms) / 1000.0)
        self._lock = asyncio.Lock()
        self._next_start_time = 0.0

    async def run(
        self,
        *,
        provider: str,
        operation: str,
        call: Callable[[], Awaitable[Any]],
        perf_state: Dict[str, Dict[str, float]] | None = None,
    ) -> Any:
        queue_wait_start = time.perf_counter()
        async with self._semaphore:
            wait_seconds = time.perf_counter() - queue_wait_start
            if self._min_interval_seconds > 0:
                async with self._lock:
                    now = time.perf_counter()
                    sleep_seconds = max(0.0, self._next_start_time - now)
                    if sleep_seconds > 0:
                        await asyncio.sleep(sleep_seconds)
                    wait_seconds += sleep_seconds
                    self._next_start_time = time.perf_counter() + self._min_interval_seconds

            call_start = time.perf_counter()
            try:
                return await call()
            finally:
                elapsed_seconds = time.perf_counter() - call_start
                if perf_state is not None:
                    bucket = perf_state.setdefault(
                        provider,
                        {"calls": 0.0, "wait_seconds": 0.0, "run_seconds": 0.0},
                    )
                    bucket["calls"] += 1.0
                    bucket["wait_seconds"] += wait_seconds
                    bucket["run_seconds"] += elapsed_seconds
                logger.info(
                    "[CL PERF] %s wait=%s run=%s operation=%s",
                    provider.capitalize(),
                    format_duration_seconds(wait_seconds),
                    format_duration_seconds(elapsed_seconds),
                    operation,
                )


_PROVIDER_GATES: Dict[str, _ProviderGate] = {}


def _get_provider_gate(provider: str) -> _ProviderGate:
    provider_key = str(provider or "").strip().lower()
    gate = _PROVIDER_GATES.get(provider_key)
    if gate is not None:
        return gate

    if provider_key == "openai":
        gate = _ProviderGate(
            concurrency=max(1, int(settings.CL_OPENAI_CONCURRENCY)),
            min_interval_ms=max(0, int(settings.CL_OPENAI_MIN_INTERVAL_MS)),
        )
    elif provider_key == "search":
        gate = _ProviderGate(
            concurrency=max(1, int(settings.CL_SEARCH_CONCURRENCY)),
            min_interval_ms=max(0, int(settings.CL_SEARCH_MIN_INTERVAL_MS)),
        )
    else:
        gate = _ProviderGate(
            concurrency=max(1, int(settings.CL_SCRAPER_CONCURRENCY)),
            min_interval_ms=max(0, int(settings.CL_SCRAPER_MIN_INTERVAL_MS)),
        )
    _PROVIDER_GATES[provider_key] = gate
    return gate


async def run_with_cl_provider_limit(
    provider: str,
    operation: str,
    call: Callable[[], Awaitable[Any]],
    *,
    perf_state: Dict[str, Dict[str, float]] | None = None,
) -> Any:
    gate = _get_provider_gate(provider)
    return await gate.run(provider=provider, operation=operation, call=call, perf_state=perf_state)
