from __future__ import annotations

import asyncio
import concurrent.futures
import inspect
import logging
import time
from typing import Any, Awaitable, Callable, Dict, TypeVar

from config.settings import settings

logger = logging.getLogger(__name__)

T = TypeVar("T")
_LAST_CALL_FAILURES: Dict[str, Dict[str, Any]] = {}


def _failure_key(provider: str, operation: str) -> str:
    return f"{provider}:{operation}"


def get_last_external_call_failure(provider: str, operation: str) -> Dict[str, Any]:
    return dict(_LAST_CALL_FAILURES.get(_failure_key(provider, operation), {}))


def _set_last_failure(
    *,
    provider: str,
    operation: str,
    attempt: int,
    max_retries: int,
    timeout: int,
    context: Dict[str, Any] | None,
    error: Exception,
) -> None:
    _LAST_CALL_FAILURES[_failure_key(provider, operation)] = {
        "provider": provider,
        "operation": operation,
        "attempt": int(attempt),
        "max_retries": int(max_retries),
        "timeout": int(timeout),
        "context": _sanitize_context(context),
        "error_type": error.__class__.__name__,
        "error_message": str(error),
        "error_repr": repr(error),
    }


def _clear_last_failure(provider: str, operation: str) -> None:
    _LAST_CALL_FAILURES.pop(_failure_key(provider, operation), None)


def _retry_delay_seconds(retry_index: int) -> int:
    return min(2**retry_index, 4)


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, str):
        normalized = " ".join(value.split())
        return normalized[:120] + ("..." if len(normalized) > 120 else "")
    if isinstance(value, dict):
        return {str(key): _sanitize_value(item) for key, item in list(value.items())[:10]}
    if isinstance(value, (list, tuple, set)):
        return [_sanitize_value(item) for item in list(value)[:10]]
    return value


def _sanitize_context(context: Dict[str, Any] | None) -> Dict[str, Any]:
    return _sanitize_value(context or {})


def _log_attempt(
    *,
    provider: str,
    operation: str,
    attempt: int,
    max_retries: int,
    context: Dict[str, Any] | None,
    error: Exception | None = None,
) -> None:
    sanitized_context = _sanitize_context(context)
    if error is None:
        logger.info(
            "external_call_succeeded provider=%s operation=%s attempt=%s max_retries=%s context=%s",
            provider,
            operation,
            attempt,
            max_retries,
            sanitized_context,
        )
        return

    logger.warning(
        "external_call_failed provider=%s operation=%s attempt=%s max_retries=%s context=%s error=%s",
        provider,
        operation,
        attempt,
        max_retries,
        sanitized_context,
        error,
    )


async def _call_async(
    *,
    provider: str,
    operation: str,
    call: Callable[[], Awaitable[T] | T],
    fallback: T,
    timeout: int,
    max_retries: int,
    context: Dict[str, Any] | None = None,
) -> T:
    last_error: Exception | None = None

    for retry_index in range(max_retries + 1):
        attempt = retry_index + 1
        try:
            result = call()
            if inspect.isawaitable(result):
                resolved = await asyncio.wait_for(result, timeout=timeout)
            else:
                resolved = result
            _log_attempt(
                provider=provider,
                operation=operation,
                attempt=attempt,
                max_retries=max_retries,
                context=context,
            )
            _clear_last_failure(provider, operation)
            return resolved
        except Exception as exc:
            last_error = exc
            _set_last_failure(
                provider=provider,
                operation=operation,
                attempt=attempt,
                max_retries=max_retries,
                timeout=timeout,
                context=context,
                error=exc,
            )
            _log_attempt(
                provider=provider,
                operation=operation,
                attempt=attempt,
                max_retries=max_retries,
                context=context,
                error=exc,
            )
            if retry_index < max_retries:
                await asyncio.sleep(_retry_delay_seconds(retry_index))

    logger.error(
        "external_call_fallback provider=%s operation=%s context=%s error=%s",
        provider,
        operation,
        _sanitize_context(context),
        last_error,
    )
    return fallback


def _call_sync(
    *,
    provider: str,
    operation: str,
    call: Callable[[], T],
    fallback: T,
    timeout: int,
    max_retries: int,
    context: Dict[str, Any] | None = None,
) -> T:
    last_error: Exception | None = None

    for retry_index in range(max_retries + 1):
        attempt = retry_index + 1
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(call)
                resolved = future.result(timeout=timeout)
            _log_attempt(
                provider=provider,
                operation=operation,
                attempt=attempt,
                max_retries=max_retries,
                context=context,
            )
            _clear_last_failure(provider, operation)
            return resolved
        except Exception as exc:
            last_error = exc
            _set_last_failure(
                provider=provider,
                operation=operation,
                attempt=attempt,
                max_retries=max_retries,
                timeout=timeout,
                context=context,
                error=exc,
            )
            _log_attempt(
                provider=provider,
                operation=operation,
                attempt=attempt,
                max_retries=max_retries,
                context=context,
                error=exc,
            )
            if retry_index < max_retries:
                time.sleep(_retry_delay_seconds(retry_index))

    logger.error(
        "external_call_fallback provider=%s operation=%s context=%s error=%s",
        provider,
        operation,
        _sanitize_context(context),
        last_error,
    )
    return fallback


async def call_openai(
    operation: str,
    call: Callable[[], Awaitable[T] | T],
    *,
    fallback: T,
    timeout: int | None = None,
    max_retries: int | None = None,
    context: Dict[str, Any] | None = None,
) -> T:
    return await _call_async(
        provider="openai",
        operation=operation,
        call=call,
        fallback=fallback,
        timeout=timeout or settings.EXTERNAL_TIMEOUT_SECONDS,
        max_retries=max_retries if max_retries is not None else settings.EXTERNAL_MAX_RETRIES,
        context=context,
    )


def call_openai_sync(
    operation: str,
    call: Callable[[], T],
    *,
    fallback: T,
    timeout: int | None = None,
    max_retries: int | None = None,
    context: Dict[str, Any] | None = None,
) -> T:
    return _call_sync(
        provider="openai",
        operation=operation,
        call=call,
        fallback=fallback,
        timeout=timeout or settings.EXTERNAL_TIMEOUT_SECONDS,
        max_retries=max_retries if max_retries is not None else settings.EXTERNAL_MAX_RETRIES,
        context=context,
    )


async def call_search(
    operation: str,
    call: Callable[[], Awaitable[T] | T],
    *,
    fallback: T,
    timeout: int | None = None,
    max_retries: int | None = None,
    context: Dict[str, Any] | None = None,
) -> T:
    return await _call_async(
        provider="search",
        operation=operation,
        call=call,
        fallback=fallback,
        timeout=timeout or settings.EXTERNAL_TIMEOUT_SECONDS,
        max_retries=max_retries if max_retries is not None else settings.EXTERNAL_MAX_RETRIES,
        context=context,
    )


def call_search_sync(
    operation: str,
    call: Callable[[], T],
    *,
    fallback: T,
    timeout: int | None = None,
    max_retries: int | None = None,
    context: Dict[str, Any] | None = None,
) -> T:
    return _call_sync(
        provider="search",
        operation=operation,
        call=call,
        fallback=fallback,
        timeout=timeout or settings.EXTERNAL_TIMEOUT_SECONDS,
        max_retries=max_retries if max_retries is not None else settings.EXTERNAL_MAX_RETRIES,
        context=context,
    )


async def call_scraper(
    operation: str,
    call: Callable[[], Awaitable[T] | T],
    *,
    fallback: T,
    timeout: int | None = None,
    max_retries: int | None = None,
    context: Dict[str, Any] | None = None,
) -> T:
    return await _call_async(
        provider="scraper",
        operation=operation,
        call=call,
        fallback=fallback,
        timeout=timeout or settings.EXTERNAL_TIMEOUT_SECONDS,
        max_retries=max_retries if max_retries is not None else settings.EXTERNAL_MAX_RETRIES,
        context=context,
    )
