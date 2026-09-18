"""Wiki progress page and demand search used to enrich step prompts."""

from __future__ import annotations

import re

from agents.memory.settings import PROGRESS_PAGE_PATH, SEARCH_HIT_LIMIT
from agents.memory.text import clip_text, format_search_hits


class MemoryProgressMixin:
    """Reads/writes the orchestrator-owned pipeline progress page."""

    workspace: str
    _project: str
    _demand: str
    _git_branch: str

    def _scope_args(self) -> list[str]:
        return ["--workspace", self.workspace, "--project", self._project]

    def _search_query(self, demand: str) -> str:
        cleaned = re.sub(r"['\"]", " ", demand or "").strip()
        return clip_text(cleaned, 300, ellipsis="")

    def _build_progress_body(
        self,
        *,
        step_name: str,
        status: str,
        git_changes: str,
        stdout: str,
    ) -> str:
        files = git_changes.strip() or "(no tracked file changes)"
        output_tail = clip_text((stdout or "").strip(), 1500) or "(no console output)"
        return (
            f"# Pipeline progress: {self._git_branch or 'unspecified-branch'}\n\n"
            f"- Demand: {self._demand or '(none)'}\n"
            f"- Branch: `{self._git_branch or 'n/a'}`\n"
            f"- Last step: {step_name} ({status})\n"
            f"- Project: `{self._project}`\n\n"
            f"## Files changed\n\n{files}\n\n"
            f"## Step output (tail)\n\n```\n{output_tail}\n```\n"
        )

    async def _read_progress(self) -> str:
        code, stdout, _ = await self._run_cli(
            ["read-page", "--path", PROGRESS_PAGE_PATH, *self._scope_args()]
        )
        if code != 0:
            return ""
        return stdout.strip()

    async def _search_demand(self, demand: str) -> str:
        query = self._search_query(demand)
        if not query:
            return ""
        code, stdout, _ = await self._run_cli(
            ["search", query, "--json", "-n", str(SEARCH_HIT_LIMIT), *self._scope_args()]
        )
        if code != 0:
            return ""
        return format_search_hits(stdout)

    async def _write_progress(
        self,
        step_name: str,
        status: str,
        git_changes: str,
        stdout: str,
    ) -> None:
        body = self._build_progress_body(
            step_name=step_name,
            status=status,
            git_changes=git_changes,
            stdout=stdout,
        )
        code, _, err = await self._run_cli(
            [
                "write-page",
                "--path",
                PROGRESS_PAGE_PATH,
                "--body",
                body,
                "--kind",
                "fact",
                "--tier",
                "episodic",
                "--tag",
                "pipeline",
                *self._scope_args(),
            ]
        )
        if code != 0:
            print(f"ai-memory write-page failed: {err[:400]}", flush=True)
