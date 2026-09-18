"""Ready-check: init data dir, start serve, poll status."""

from __future__ import annotations

import asyncio
import os

from agents.memory.settings import binary_available


class MemoryServeMixin:
    """Brings the local ai-memory server to a usable state (fail-open)."""

    binary: str
    data_dir: str
    serve_poll_attempts: int
    serve_poll_interval: float
    _lock: asyncio.Lock
    _ready: bool
    _serve_proc: asyncio.subprocess.Process | None

    async def ensure_ready(self) -> bool:
        async with self._lock:
            if self._serve_proc is not None and self._serve_proc.returncode is not None:
                self._ready = False
                self._serve_proc = None
            if self._ready:
                return True
            if not binary_available(self.binary):
                print(f"ai-memory binary '{self.binary}' is not on PATH", flush=True)
                return False
            try:
                os.makedirs(self.data_dir, exist_ok=True)
            except OSError as exc:
                print(f"ai-memory data dir error: {exc}", flush=True)
                return False
            init_code, _, init_err = await self._run_cli(["init"])
            if init_code != 0:
                print(f"ai-memory init failed: {init_err[:400]}", flush=True)
                # Continue — a previous init may already exist.
            if await self._status_ok():
                self._ready = True
                return True
            try:
                await self._start_serve()
            except Exception as exc:
                print(f"ai-memory serve failed to start: {exc}", flush=True)
                return False
            for _ in range(max(1, self.serve_poll_attempts)):
                if await self._status_ok():
                    self._ready = True
                    return True
                await asyncio.sleep(self.serve_poll_interval)
            print(
                "ai-memory server did not become ready; memory hooks disabled for this run",
                flush=True,
            )
            return False
