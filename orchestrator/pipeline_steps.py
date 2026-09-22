"""Single TDD pipeline step: run the agent, persist status, notify Telegram."""

from __future__ import annotations

import html
import re

from orchestrator.paths import PROJECT_DIR
from orchestrator.workspace import GitWorkspace, git_workspace


class PipelineStepExecutor:
    """Runs one TDD step and turns its result into a Telegram status message."""

    def __init__(self, workspace: GitWorkspace | None = None):
        self.workspace = workspace or git_workspace

    def mode_label(self, mode: str, *, hard_mode: str) -> str:
        return "Hard (Thorough Review)" if mode == hard_mode else "Easy (Fast)"

    def branch_name(self, demand: str) -> str:
        clean_name = re.sub(r'[^a-zA-Z0-9]', '-', demand.lower())[:30].strip('-')
        return f"feature/{clean_name}"

    def last_completed_name(self, idx: int, step_name: str, pipeline_config: list[dict]) -> str:
        return step_name if idx == 0 else pipeline_config[idx - 1]["step_name"]

    def format_summary(
        self,
        step_name: str,
        *,
        pytest_sum: str,
        git_changes: str,
        pr_url: str,
        stdout_str: str,
    ) -> str:
        summary_parts = [f"✅ <b>{step_name} completed successfully!</b>"]
        if git_changes:
            summary_parts.append(f"<b>Files changed:</b>\n{git_changes}")
        if pytest_sum:
            summary_parts.append(f"<b>Tests status:</b> <code>{pytest_sum}</code>")
        if pr_url:
            summary_parts.append(f"<b>PR Created:</b> <a href=\"{pr_url}\">{pr_url}</a>")
        if not pytest_sum and not git_changes and not pr_url:
            stdout_lines = [line.strip() for line in stdout_str.splitlines() if line.strip()]
            last_lines = "\n".join(stdout_lines[-7:]) if stdout_lines else "No console output."
            last_lines_escaped = html.escape(last_lines)
            last_lines_formatted = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', last_lines_escaped)
            summary_parts.append(f"<b>Output Tail:</b>\n{last_lines_formatted}")
        return "\n\n".join(summary_parts)

    async def persist(
        self,
        host,
        repo_url,
        demand,
        step_name,
        idx,
        steps_status,
        git_branch,
        mode,
        pipeline_config,
        status: str,
    ) -> None:
        steps_status[step_name] = status
        host.save_session(
            repo_url,
            demand,
            self.last_completed_name(idx, step_name, pipeline_config) if status != "success" else step_name,
            steps_status,
            git_branch,
            mode=mode,
        )

    async def execute(
        self,
        update,
        step: dict,
        idx: int,
        *,
        demand: str,
        repo_url: str,
        git_branch: str,
        mode: str,
        steps_status: dict,
        pipeline_config: list[dict],
        host,
        project_dir: str = PROJECT_DIR,
    ) -> str:
        """Runs one pipeline step. Returns 'success', 'failed', or 'aborted'."""
        step_name = step["step_name"]
        await update.message.reply_text(
            f"⏳ <b>Executing:</b> {step_name}\n🔧 <b>CLI:</b> <code>{step['tool']}</code> | "
            f"<b>Model:</b> <code>{step['model']}</code> (Thinking: {step['reasoning_budget']})",
            parse_mode="HTML",
        )

        prompt_content = step["prompt"].format(
            demand=demand,
            repo_owner_name=host.extract_owner_repo(repo_url) or repo_url,
        )

        try:
            agent_cli = host.AgentRegistry.get_agent(step["tool"])
            command = agent_cli.build_command(
                prompt=prompt_content,
                model=step["model"],
                reasoning_budget=step["reasoning_budget"],
                timeout=step.get("timeout"),
            )
            returncode, stdout_str, stderr_str = await host.run_command_and_stream(command, cwd=project_dir)

            if returncode != 0:
                await self.persist(
                    host, repo_url, demand, step_name, idx, steps_status, git_branch, mode, pipeline_config, "failed"
                )
                error_msg = f"⚠️ <b>Failure in step {step_name}:</b>\n\n"
                if stderr_str.strip():
                    error_msg += f"<b>Stderr:</b>\n<pre>{html.escape(stderr_str[:800])}</pre>\n\n"
                if stdout_str.strip():
                    error_msg += f"<b>Stdout:</b>\n<pre>{html.escape(stdout_str[:800])}</pre>"
                await update.message.reply_text(error_msg, parse_mode="HTML")
                return "failed"

            abort_reason = self.workspace.read_abort_reason(project_dir)
            if abort_reason is not None:
                await self.persist(
                    host, repo_url, demand, step_name, idx, steps_status, git_branch, mode, pipeline_config, "aborted"
                )
                await update.message.reply_text(
                    f"🚫 <b>Pipeline Aborted by Architect Review:</b>\n\n"
                    f"<b>Reason:</b>\n<pre>{html.escape(abort_reason[:1500])}</pre>",
                    parse_mode="HTML",
                )
                return "aborted"

            await self.persist(
                host, repo_url, demand, step_name, idx, steps_status, git_branch, mode, pipeline_config, "success"
            )
            pytest_sum = host.get_pytest_summary(stdout_str)
            git_changes = host.get_git_changes()
            pr_url = host.get_pr_url()
            await update.message.reply_text(
                self.format_summary(
                    step_name,
                    pytest_sum=pytest_sum,
                    git_changes=git_changes,
                    pr_url=pr_url,
                    stdout_str=stdout_str,
                ),
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            return "success"
        except Exception as e:
            await self.persist(
                host, repo_url, demand, step_name, idx, steps_status, git_branch, mode, pipeline_config, "failed"
            )
            await update.message.reply_text(f"❌ System error in step {step_name}: {str(e)}")
            return "failed"
