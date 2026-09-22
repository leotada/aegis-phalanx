"""Fetch GitHub PR metadata/diff and send review text to Telegram."""

from __future__ import annotations

import asyncio

from orchestrator.markdown import MarkdownRenderer, markdown_renderer


class PullRequestGateway:
    """Loads a pull request's metadata and diff, and delivers review text to Telegram."""

    def __init__(self, renderer: MarkdownRenderer | None = None):
        self.renderer = renderer or markdown_renderer

    async def fetch(
        self,
        repo_owner_name: str,
        pr_number: int,
        project_dir: str,
        max_diff_chars: int = 120_000,
    ) -> str:
        """Fetches PR metadata and diff via gh for injection into the review prompt."""
        sections: list[str] = []

        view_proc = await asyncio.create_subprocess_exec(
            "gh", "pr", "view", str(pr_number), "--repo", repo_owner_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        view_out, view_err = await view_proc.communicate()
        if view_proc.returncode == 0:
            sections.append(view_out.decode("utf-8", errors="replace").strip())
        else:
            err = view_err.decode("utf-8", errors="replace").strip()
            sections.append(f"(Could not fetch PR metadata: {err[:500]})")

        diff_proc = await asyncio.create_subprocess_exec(
            "gh", "pr", "diff", str(pr_number), "--repo", repo_owner_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=project_dir,
        )
        diff_out, diff_err = await diff_proc.communicate()
        if diff_proc.returncode == 0:
            diff_text = diff_out.decode("utf-8", errors="replace").strip()
            if len(diff_text) > max_diff_chars:
                diff_text = diff_text[:max_diff_chars] + "\n\n… (diff truncated)"
            sections.append("--- Diff ---\n" + diff_text)
        else:
            err = diff_err.decode("utf-8", errors="replace").strip()
            sections.append(f"(Could not fetch PR diff: {err[:500]})")

        return "\n\n".join(sections)

    async def send(self, update, review_text: str) -> None:
        """Sends the review text to Telegram as formatted Markdown, splitting into chunks if needed."""
        for chunk in self.renderer.render(review_text):
            await update.message.reply_text(
                chunk, parse_mode="HTML", disable_web_page_preview=True
            )


pull_requests = PullRequestGateway()
