import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

try:
    import psutil
except Exception:  # pragma: no cover - optional dependency fallback
    psutil = None  # type: ignore[assignment]

from core.logging import get_logger

logger = get_logger(__name__)
_PROCESS = None
_PROCESS_CPU_PRIMED = False
_SYSTEM_CPU_PRIMED = False


def _get_process():
    global _PROCESS
    if psutil is None:
        return None
    if _PROCESS is None:
        try:
            _PROCESS = psutil.Process(os.getpid())
        except Exception:
            _PROCESS = None
    return _PROCESS


def _prime_cpu_counters() -> None:
    global _PROCESS_CPU_PRIMED, _SYSTEM_CPU_PRIMED
    if psutil is None:
        return
    try:
        if not _SYSTEM_CPU_PRIMED:
            psutil.cpu_percent(interval=0.05)
            _SYSTEM_CPU_PRIMED = True
    except Exception:
        pass

    process = _get_process()
    if process is None:
        return
    try:
        if not _PROCESS_CPU_PRIMED:
            process.cpu_percent(interval=0.05)
            _PROCESS_CPU_PRIMED = True
    except Exception:
        pass


def _safe_round(value: float) -> float:
    return round(float(value), 1)


def format_mb(value: float) -> str:
    return f"{_safe_round(value)}MB"


def get_process_memory_mb() -> float:
    if psutil is None:
        return 0.0
    try:
        process = _get_process()
        if process is None:
            return 0.0
        return process.memory_info().rss / (1024 * 1024)
    except Exception:
        return 0.0


def get_process_cpu_percent() -> float:
    if psutil is None:
        return 0.0
    _prime_cpu_counters()
    try:
        process = _get_process()
        if process is None:
            return 0.0
        return process.cpu_percent(interval=None)
    except Exception:
        return 0.0


def get_system_health_snapshot() -> Dict[str, Any]:
    if psutil is None:
        return {
            "cpu_percent": 0.0,
            "memory_percent": 0.0,
            "memory_used_mb": 0.0,
            "memory_total_mb": 0.0,
            "process_memory_mb": 0.0,
            "process_cpu_percent": 0.0,
        }

    _prime_cpu_counters()
    virtual_memory = psutil.virtual_memory()
    return {
        "cpu_percent": _safe_round(psutil.cpu_percent(interval=None)),
        "memory_percent": _safe_round(virtual_memory.percent),
        "memory_used_mb": _safe_round(virtual_memory.used / (1024 * 1024)),
        "memory_total_mb": _safe_round(virtual_memory.total / (1024 * 1024)),
        "process_memory_mb": _safe_round(get_process_memory_mb()),
        "process_cpu_percent": _safe_round(get_process_cpu_percent()),
    }


@dataclass
class ResearchDiagnostics:
    research_id: str
    session_id: str
    topic: str
    section: str
    started_at: float = field(default_factory=time.perf_counter)
    peak_memory_mb: float = 0.0
    urls_processed: int = 0
    documents_processed: int = 0
    openai_calls: int = 0
    current_stage: str = "Queued"
    current_activity: str = "Waiting for worker"
    progress_percentage: int = 0
    stage_timings_ms: Dict[str, int] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def elapsed_seconds(self) -> float:
        return _safe_round(time.perf_counter() - self.started_at)

    def snapshot(self) -> Dict[str, Any]:
        current_memory_mb = _safe_round(get_process_memory_mb())
        self.peak_memory_mb = max(self.peak_memory_mb, current_memory_mb)
        system_health = get_system_health_snapshot()
        return {
            "research_id": self.research_id,
            "session_id": self.session_id,
            "topic": self.topic,
            "section": self.section,
            "stage": self.current_stage,
            "current_activity": self.current_activity,
            "elapsed_seconds": self.elapsed_seconds(),
            "progress_percentage": int(self.progress_percentage),
            "peak_memory_mb": _safe_round(self.peak_memory_mb),
            "current_memory_mb": current_memory_mb,
            "cpu_percent": _safe_round(system_health.get("process_cpu_percent", 0.0)),
            "urls_processed": int(self.urls_processed),
            "documents_processed": int(self.documents_processed),
            "openai_calls": int(self.openai_calls),
            "stage_timings_ms": dict(self.stage_timings_ms),
            "system": system_health,
            "metadata": dict(self.metadata),
        }

    def mark_stage(
        self,
        stage: str,
        *,
        activity: str,
        progress: int,
        stage_duration_ms: Optional[int] = None,
        urls_processed: Optional[int] = None,
        documents_processed: Optional[int] = None,
        openai_calls_increment: int = 0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        self.current_stage = str(stage).strip() or self.current_stage
        self.current_activity = str(activity).strip() or self.current_activity
        self.progress_percentage = max(0, min(int(progress), 100))
        if stage_duration_ms is not None:
            self.stage_timings_ms[str(stage)] = max(int(stage_duration_ms), 0)
        if urls_processed is not None:
            self.urls_processed = max(int(urls_processed), 0)
        if documents_processed is not None:
            self.documents_processed = max(int(documents_processed), 0)
        if openai_calls_increment:
            self.openai_calls += max(int(openai_calls_increment), 0)
        if metadata:
            self.metadata.update(metadata)

        snapshot = self.snapshot()
        logger.info(
            "[%s]\nStage: %s\nActivity: %s\nProgress: %s%%\nElapsed: %ss\nRAM: %s\nPeak RAM: %s\nCPU: %s%%\nURLs Processed: %s\nDocuments Processed: %s\nOpenAI Calls: %s",
            self.research_id,
            snapshot["stage"],
            snapshot["current_activity"],
            snapshot["progress_percentage"],
            snapshot["elapsed_seconds"],
            format_mb(snapshot["current_memory_mb"]),
            format_mb(snapshot["peak_memory_mb"]),
            snapshot["cpu_percent"],
            snapshot["urls_processed"],
            snapshot["documents_processed"],
            snapshot["openai_calls"],
        )
        return snapshot


def log_startup_diagnostics(context: str, extra: Optional[Dict[str, Any]] = None) -> None:
    payload = {
        "context": context,
        "event": "startup_diagnostics",
        "snapshot": get_system_health_snapshot(),
    }
    if extra:
        payload["extra"] = extra
    logger.info("startup_diagnostics %s", json.dumps(payload, ensure_ascii=True))


def log_shutdown_diagnostics(context: str, extra: Optional[Dict[str, Any]] = None) -> None:
    payload = {
        "context": context,
        "event": "shutdown_diagnostics",
        "snapshot": get_system_health_snapshot(),
    }
    if extra:
        payload["extra"] = extra
    logger.info("shutdown_diagnostics %s", json.dumps(payload, ensure_ascii=True))


ProgressCallback = Callable[[Dict[str, Any]], None]
