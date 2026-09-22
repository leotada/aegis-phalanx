"""Live ai-memory middleware: bind a run, enrich prompts, record progress."""

from __future__ import annotations

import asyncio
import os

from agents.config import env_float, env_int
from agents.memory.cli import MemoryCliMixin
from agents.memory.progress import MemoryProgressMixin
from agents.memory.protocol import MemoryMiddleware
from agents.memory.serve import MemoryServeMixin
from agents.memory.settings import (
    DEFAULT_CLI_TIMEOUT,
    DEFAULT_CONTEXT_CHARS,
    DEFAULT_DATA_DIR,
    DEFAULT_SERVER_URL,
    DEFAULT_WORKSPACE,
    MEMORY_PREAMBLE,
    PROGRESS_PAGE_PATH,
    ai_memory_binary,
)
from agents.memory.text import clip_text, project_slug


class AIMemoryManager(
    MemoryCliMixin,
    MemoryServeMixin,
    MemoryProgressMixin,
    MemoryMiddleware,
):
    """Talks to the real ai-memory CLI (init/serve/search/read-page/write-page)."""

    enabled = True

    def __init__(
        self,
        *,
        binary: str | None = None,
        data_dir: str | None = None,
        server_url: str | None = None,
        workspace: str | None = None,
        context_chars: int | None = None,
        cli_timeout: float | None = None,
        serve_poll_attempts: int | None = None,
        serve_poll_interval: float | None = None,
    ) -> None:
        self.binary = binary or ai_memory_binary()
        self.data_dir = data_dir or os.environ.get("AI_MEMORY_DATA_DIR", DEFAULT_DATA_DIR)
        self.server_url = server_url or os.environ.get("AI_MEMORY_SERVER_URL", DEFAULT_SERVER_URL)
        self.workspace = workspace or os.environ.get("AI_MEMORY_WORKSPACE", DEFAULT_WORKSPACE)
        self.context_chars = (
            context_chars
            if context_chars is not None
            else env_int("AI_MEMORY_CONTEXT_CHARS", DEFAULT_CONTEXT_CHARS)
        )
        self.cli_timeout = (
            cli_timeout
            if cli_timeout is not None
            else env_float("AI_MEMORY_CLI_TIMEOUT", DEFAULT_CLI_TIMEOUT)
        )
        self.serve_poll_attempts = (
            serve_poll_attempts
            if serve_poll_attempts is not None
            else env_int("AI_MEMORY_SERVE_POLL_ATTEMPTS", 10)
        )
        self.serve_poll_interval = (
            serve_poll_interval
            if serve_poll_interval is not None
            else env_float("AI_MEMORY_SERVE_POLL_INTERVAL", 0.5)
        )
        self._lock = asyncio.Lock()
        self._ready = False
        self._serve_proc: asyncio.subprocess.Process | None = None
        self._cwd = ""
        self._project = "project"
        self._demand = ""
        self._git_branch = ""
        self._begun = False
        self._page_path = PROGRESS_PAGE_PATH
        self._last_snapshot = None

    async def begin_run(
        self,
        *,
        cwd: str,
        project: str,
        demand: str,
        git_branch: str,
        is_resume: bool = False,
        page_path: str | None = None,
    ) -> None:
        try:
            self._cwd = cwd
            self._project = project_slug(project)
            self._demand = demand
            self._git_branch = git_branch
            self._page_path = page_path or PROGRESS_PAGE_PATH
            self._last_snapshot = None
            if not await self.ensure_ready():
                return
            self._begun = True
            if not is_resume:
                await self._write_progress("Pipeline started", "started", "", "")
        except Exception as exc:
            print(f"ai-memory begin_run failed: {exc}", flush=True)

    async def enrich_prompt(self, prompt: str, *, demand: str, step_name: str) -> str:
        try:
            if not await self.ensure_ready():
                return prompt
            parts: list[str] = []
            progress = await self._read_progress()
            if progress:
                parts.append("Last pipeline snapshot:\n" + progress)
            related = await self._search_demand(demand)
            if related:
                parts.append("Related memory:\n" + related)
            if not parts:
                return prompt
            context = clip_text("\n\n".join(parts), self.context_chars)
            return (
                f"{MEMORY_PREAMBLE}\n{context}\n\n"
                f"YOUR TASK THIS STEP ({step_name}):\n{prompt}"
            )
        except Exception as exc:
            print(f"ai-memory enrich_prompt failed: {exc}", flush=True)
            return prompt

    async def after_step(
        self,
        *,
        step_name: str,
        status: str,
        git_changes: str = "",
        stdout: str = "",
    ) -> None:
        try:
            if not self._begun:
                return
            if not await self.ensure_ready():
                return
            await self._write_progress(step_name, status, git_changes, stdout)
        except Exception as exc:
            print(f"ai-memory after_step failed: {exc}", flush=True)

    async def end_run(self, *, status: str) -> None:
        try:
            if not self._begun:
                return
            if not await self.ensure_ready():
                return
            if self._last_snapshot is None:
                step_name, step_status, git_changes, stdout = "Pipeline finished", status, "", ""
            else:
                step_name, step_status, git_changes, stdout = self._last_snapshot
            await self._write_progress(
                step_name,
                step_status,
                git_changes,
                stdout,
                run_status=status,
            )
            self._begun = False
        except Exception as exc:
            print(f"ai-memory end_run failed: {exc}", flush=True)
