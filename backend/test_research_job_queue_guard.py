from fastapi import HTTPException

from api import analyze


def test_background_job_queue_guard_allows_when_redis_available(monkeypatch):
    monkeypatch.setattr(analyze, "ping_redis", lambda: True)

    analyze._ensure_background_job_queue_available()


def test_background_job_queue_guard_raises_503_when_redis_unavailable(monkeypatch):
    monkeypatch.setattr(analyze, "ping_redis", lambda: False)

    try:
        analyze._ensure_background_job_queue_available()
    except HTTPException as exc:
        assert exc.status_code == 503
        assert "Redis is not reachable" in str(exc.detail)
    else:
        raise AssertionError("Expected HTTPException when Redis is unavailable.")
