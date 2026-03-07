"""Minimal deployment worker entrypoint used by on-prem compose and Helm assets."""

from __future__ import annotations

import os
import time


def run_worker(*, poll_interval_seconds: float = 15.0, once: bool = False) -> None:
    """Run the background worker heartbeat loop.

    Example:
        >>> run_worker(poll_interval_seconds=0.0, once=True) is None
        True
    """

    if once:
        return
    while True:  # pragma: no branch - intentionally long-lived worker process
        time.sleep(max(1.0, float(poll_interval_seconds)))


def main() -> None:
    """Console entrypoint for the deployment worker."""

    run_worker(
        poll_interval_seconds=float(os.getenv("ARCHON_WORKER_POLL_SECONDS", "15")),
        once=str(os.getenv("ARCHON_WORKER_ONCE", "")).strip().lower() == "true",
    )


if __name__ == "__main__":
    main()
