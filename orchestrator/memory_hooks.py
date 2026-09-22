"""Thin façade over MemoryMiddleware for pipeline/review call sites."""

from __future__ import annotations

from agents.memory.protocol import MemoryMiddleware


class PipelineMemory:
    """Records orchestrator-owned wiki progress around a pipeline or review run."""

    def __init__(self, middleware: MemoryMiddleware) -> None:
        self._mw = middleware

    async def begin(self, **kwargs) -> None:
        await self._mw.begin_run(**kwargs)

    async def enrich(self, prompt: str, *, demand: str, step_name: str) -> str:
        return await self._mw.enrich_prompt(prompt, demand=demand, step_name=step_name)

    async def record(self, **kwargs) -> None:
        await self._mw.after_step(**kwargs)

    async def finish(self, status: str) -> None:
        await self._mw.end_run(status=status)

    async def fail(self, **kwargs) -> None:
        status = kwargs.get("status", "failed")
        await self.record(**kwargs)
        await self.finish(status)
