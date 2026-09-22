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
    _page_path: str
    _last_snapshot: tuple[str, str, str, str] | None

    def _scope_args(self) -> list[str]:
        return ["--workspace", self.workspace, "--project", self._project]

    def _progress_page(self) -> str:
        return getattr(self, "_page_path", "") or PROGRESS_PAGE_PATH

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
        run_status: str = "",
    ) -> str:
        files = git_changes.strip() or "(no tracked file changes)"
        output_tail = clip_text((stdout or "").strip(), 1500) or "(no console output)"
        run_line = f"- Run: {run_status}\n" if run_status else ""
        return (
            f"# Pipeline progress: {self._git_branch or 'unspecified-branch'}\n\n"
            f"- Demand: {self._demand or '(none)'}\n"
            f"- Branch: `{self._git_branch or 'n/a'}`\n"
            f"{run_line}"
            f"- Last step: {step_name} ({status})\n"
            f"- Project: `{self._project}`\n\n"
            f"## Files changed\n\n{files}\n\n"
            f"## Step output (tail)\n\n```\n{output_tail}\n```\n"
        )

    async def _read_progress(self) -> str:
        code, stdout, _ = await self._run_cli(
            ["read-page", "--path", self._progress_page(), *self._scope_args()]
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
        run_status: str = "",
    ) -> None:
        self._last_snapshot = (step_name, status, git_changes, stdout)
        body = self._build_progress_body(
            step_name=step_name,
            status=status,
            git_changes=git_changes,
            stdout=stdout,
            run_status=run_status,
        )
        code, _, err = await self._run_cli(
            [
                "write-page",
                "--path",
                self._progress_page(),
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
