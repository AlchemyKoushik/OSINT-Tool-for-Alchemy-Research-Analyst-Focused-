from __future__ import annotations

import os
import sys
import time
from pathlib import Path


def main() -> int:
    heartbeat_path = Path(os.getenv("WORKER_HEARTBEAT_FILE", "/tmp/osint-worker-heartbeat")).expanduser()
    max_age_seconds = int(os.getenv("WORKER_HEARTBEAT_MAX_AGE_SECONDS", "120"))

    if not heartbeat_path.exists():
        print(f"Heartbeat file is missing: {heartbeat_path}", file=sys.stderr)
        return 1

    age_seconds = time.time() - heartbeat_path.stat().st_mtime
    if age_seconds > max_age_seconds:
        print(
            f"Worker heartbeat is stale: age_seconds={age_seconds:.1f} max_age_seconds={max_age_seconds}",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
