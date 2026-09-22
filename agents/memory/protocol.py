"""Memory middleware contract. Disabled path is fail-open no-op."""

from __future__ import annotations


class MemoryMiddleware:
    """No-op base used when ai-memory is disabled or unavailable."""

    enabled = False

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
        return None

    async def enrich_prompt(self, prompt: str, *, demand: str, step_name: str) -> str:
        return prompt

    async def after_step(
        self,
        *,
        step_name: str,
        status: str,
        git_changes: str = "",
        stdout: str = "",
    ) -> None:
        return None

    async def end_run(self, *, status: str) -> None:
        return None


class DisabledMemoryManager(MemoryMiddleware):
    """Explicit alias for the fail-open disabled path."""
