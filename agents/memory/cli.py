"""Subprocess adapter for the ai-memory CLI and HTTP serve process."""

from __future__ import annotations

import asyncio
import os
import signal


class MemoryCliMixin:
    """Runs `ai-memory` commands and optionally starts `serve`."""

    binary: str
    data_dir: str
    server_url: str
    workspace: str
    cli_timeout: float
    _cwd: str
    _serve_proc: asyncio.subprocess.Process | None

    def _bind_address(self) -> str:
        return self.server_url.replace("https://", "").replace("http://", "").rstrip("/")

    def _cli_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["AI_MEMORY_DATA_DIR"] = self.data_dir
        env["AI_MEMORY_SERVER_URL"] = self.server_url
        return env

    def _base_args(self) -> list[str]:
        return [self.binary, "--data-dir", self.data_dir]

    async def _run_cli(
        self,
        args: list[str],
        *,
        stdin: str | None = None,
        timeout: float | None = None,
        cwd: str | None = None,
    ) -> tuple[int, str, str]:
        command = self._base_args() + args
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.PIPE if stdin is not None else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd or (self._cwd or None),
                env=self._cli_env(),
            )
            payload = stdin.encode("utf-8") if stdin is not None else None
            stdout_b, stderr_b = await asyncio.wait_for(
                process.communicate(payload),
                timeout=timeout if timeout is not None else self.cli_timeout,
            )
        except Exception as exc:
            print(f"ai-memory CLI error ({args[:1]}): {exc}", flush=True)
            return 1, "", str(exc)
        stdout = stdout_b.decode("utf-8", errors="replace") if stdout_b else ""
        stderr = stderr_b.decode("utf-8", errors="replace") if stderr_b else ""
        return process.returncode or 0, stdout, stderr

    async def _status_ok(self) -> bool:
        code, _, _ = await self._run_cli(["status", "--json"])
        return code == 0

    async def _start_serve(self) -> None:
        if self._serve_proc is not None and self._serve_proc.returncode is None:
            return
        os.makedirs(self.data_dir, exist_ok=True)
        log_path = os.path.join(self.data_dir, "serve.log")
        log_file = open(log_path, "ab")
        try:
            self._serve_proc = await asyncio.create_subprocess_exec(
                *self._base_args(),
                "serve",
                "--transport",
                "http",
                "--bind",
                self._bind_address(),
                "--workspace",
                self.workspace,
                stdout=log_file,
                stderr=log_file,
                cwd=self._cwd or self.data_dir,
                env=self._cli_env(),
                start_new_session=True,
            )
        finally:
            log_file.close()

    def stop_serve(self) -> None:
        """Stops the serve process this manager started. Safe to call more than once."""
        proc = self._serve_proc
        self._serve_proc = None
        self._ready = False
        if proc is None or proc.returncode is not None:
            return
        pid = getattr(proc, "pid", None)
        if not isinstance(pid, int) or pid <= 0:
            return
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
