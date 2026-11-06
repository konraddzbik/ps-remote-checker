"""Small throughput test against Cloudflare's public speed-test endpoints.

The PS5 *uploads* the video stream, the PS Portal *downloads* it, so the home
side cares about upload and the remote side about download.
"""
from __future__ import annotations

import threading
import time
import urllib.error
import urllib.request

from .netinfo import USER_AGENT

DOWN_URL = "https://speed.cloudflare.com/__down?bytes={n}"
UP_URL = "https://speed.cloudflare.com/__up"
CHUNK = 64 * 1024


def _run_parallel(worker, streams: int, duration: float) -> float | None:
    total = [0]
    lock = threading.Lock()
    errors = []
    stop_at = time.perf_counter() + duration

    def wrapped():
        try:
            worker(stop_at, total, lock)
        except Exception as e:  # noqa: BLE001 - report any failure, keep other streams going
            errors.append(e)

    threads = [threading.Thread(target=wrapped, daemon=True) for _ in range(streams)]
    start = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join(duration + 15)
    elapsed = time.perf_counter() - start
    if total[0] == 0:
        if errors:
            raise errors[0]
        return None
    return round(total[0] * 8 / elapsed / 1_000_000, 1)


def download_mbps(duration: float = 6.0, streams: int = 4) -> float | None:
    def worker(stop_at, total, lock):
        while time.perf_counter() < stop_at:
            req = urllib.request.Request(DOWN_URL.format(n=25_000_000), headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=10) as resp:
                while time.perf_counter() < stop_at:
                    chunk = resp.read(CHUNK)
                    if not chunk:
                        break
                    with lock:
                        total[0] += len(chunk)
    return _run_parallel(worker, streams, duration)


def upload_mbps(duration: float = 6.0, streams: int = 4) -> float | None:
    payload = b"0" * 2_000_000

    def worker(stop_at, total, lock):
        while time.perf_counter() < stop_at:
            req = urllib.request.Request(UP_URL, data=payload, method="POST", headers={
                "User-Agent": USER_AGENT, "Content-Type": "application/octet-stream"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                resp.read()
            with lock:
                total[0] += len(payload)
    return _run_parallel(worker, streams, duration)


def run(duration: float = 6.0) -> dict:
    out = {"down_mbps": None, "up_mbps": None, "error": None}
    try:
        out["down_mbps"] = download_mbps(duration)
        out["up_mbps"] = upload_mbps(duration)
    except (urllib.error.URLError, OSError) as e:
        out["error"] = str(getattr(e, "reason", e))
    return out
