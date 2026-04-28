import time

import requests

BASE_URL = "http://127.0.0.1:8000"
REQUEST_TIMEOUT_SECONDS = 120


def log(message: str) -> None:
    print(message, flush=True)


def post_json(path: str, payload: dict) -> requests.Response | None:
    url = f"{BASE_URL}{path}"
    try:
        response = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT_SECONDS)
        return response
    except requests.RequestException as exc:
        log(f"[ERROR] Request to {url} failed: {exc}")
        return None


def delete_request(path: str) -> requests.Response | None:
    url = f"{BASE_URL}{path}"
    try:
        response = requests.delete(url, timeout=REQUEST_TIMEOUT_SECONDS)
        return response
    except requests.RequestException as exc:
        log(f"[ERROR] Request to {url} failed: {exc}")
        return None


def print_response(prefix: str, response: requests.Response) -> None:
    log(f"{prefix} status={response.status_code}")
    try:
        body = response.json()
    except ValueError:
        body = response.text
    log(f"{prefix} body={body}")


def test_pipeline() -> None:
    log("")
    log("[START] Full backend pipeline test")
    log("")

    session_id = ""

    log("[STEP 1] Calling /api/research")
    research_response = post_json(
        "/api/research",
        {
            "topic": "AI startups in India",
            "section": "trends",
            "debug": False,
        },
    )
    if research_response is None:
        log("[FAIL] Could not reach /api/research")
        return
    if research_response.status_code != 200:
        print_response("[FAIL] /api/research", research_response)
        return

    research_data = research_response.json()
    session_id = str(research_data.get("session_id", "")).strip()
    print_response("[OK] /api/research", research_response)

    if not session_id:
        log("[FAIL] No session_id returned from /api/research")
        return

    log(f"[INFO] session_id={session_id}")
    time.sleep(2)

    log("")
    log("[STEP 2] Calling /api/analyze with returned session_id")
    analyze_response = post_json(
        "/api/analyze",
        {
            "topic": "AI startups in India",
            "section": "drivers",
            "session_id": session_id,
            "debug": False,
        },
    )
    if analyze_response is None:
        log("[FAIL] Could not reach /api/analyze")
        return
    if analyze_response.status_code != 200:
        print_response("[FAIL] /api/analyze", analyze_response)
        return

    print_response("[OK] /api/analyze", analyze_response)

    log("")
    log("[STEP 3] Calling DELETE /api/sessions/{session_id}")
    cleanup_response = delete_request(f"/api/sessions/{session_id}")
    if cleanup_response is None:
        log("[WARN] Cleanup request could not be completed")
        return
    if cleanup_response.status_code != 200:
        print_response("[WARN] cleanup", cleanup_response)
        return

    print_response("[OK] cleanup", cleanup_response)
    log("")
    log("[DONE] Full backend pipeline test complete")
    log("")


if __name__ == "__main__":
    test_pipeline()
