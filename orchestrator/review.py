"""PR review runner. Collaborators are resolved from the composition-root host."""

from __future__ import annotations

import asyncio
import html
import os

from orchestrator.tasks import ActiveTasks
from orchestrator.workspace import GitWorkspace, git_workspace


class ReviewRunner:
    """Clones a repository, checks out a pull request, and returns only the review text."""

    def __init__(self, workspace: GitWorkspace | None = None):
        self.workspace = workspace or git_workspace

    async def _checkout_pr(self, repo_owner_name: str, pr_number: int, project_dir: str, host) -> tuple[int, bytes]:
        checkout_proc = await asyncio.create_subprocess_exec(
            "gh", "pr", "checkout", str(pr_number), "--repo", repo_owner_name,
            cwd=project_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        _, checkout_err = await host._communicate_or_cancel(checkout_proc)
        return checkout_proc.returncode or 0, checkout_err

    async def execute(self, update, context, repo_url: str, pr_number: int, host) -> None:
        """Clones a repo, runs a single PR review step, and returns only the review text."""
        chat_id = str(update.effective_chat.id)
        current_task = asyncio.current_task()
        tasks = ActiveTasks(host.ACTIVE_TASKS)
        tasks.track(chat_id, current_task)

        project_dir = self.workspace.project_dir
        repo_owner_name = host.extract_owner_repo(repo_url) or repo_url
        github_token = os.environ.get("GITHUB_TOKEN")
        review_config = host.resolve_review_pipeline_config()
        step = review_config[0]

        try:
            auth_repo_url, _auth_method, auth_error = await host.resolve_clone_url(repo_url, github_token)
            if auth_error:
                await update.message.reply_text(f"❌ Error: {auth_error}", parse_mode="HTML")
                return

            if os.path.exists(project_dir):
                await self.workspace.remove(
                    project_dir,
                    start_new_session=True,
                    wait_fn=host._wait_or_cancel,
                )

            returncode, _stdout_c, stderr_c = await self.workspace.clone(
                auth_repo_url,
                project_dir,
                start_new_session=True,
                communicate_fn=host._communicate_or_cancel,
            )
            if returncode != 0:
                err = stderr_c.decode("utf-8", errors="replace")[:800]
                await update.message.reply_text(
                    f"❌ <b>Failed to clone repository.</b>\n<b>Stderr:</b>\n<pre>{html.escape(err)}</pre>",
                    parse_mode="HTML",
                )
                return

            checkout_code, checkout_err = await self._checkout_pr(repo_owner_name, pr_number, project_dir, host)
            if checkout_code != 0:
                err = checkout_err.decode("utf-8", errors="replace")[:800]
                await update.message.reply_text(
                    f"❌ <b>Failed to checkout PR #{pr_number}.</b>\n<b>Stderr:</b>\n<pre>{html.escape(err)}</pre>",
                    parse_mode="HTML",
                )
                return

            prompt_content = step["prompt"].format(
                pr_number=pr_number,
                repo_owner_name=repo_owner_name,
                pr_context=await host.fetch_pr_context(repo_owner_name, pr_number, project_dir),
            )

            agent_cli = host.AgentRegistry.get_agent(step["tool"])
            command = agent_cli.build_command(
                prompt=prompt_content,
                model=step["model"],
                reasoning_budget=step["reasoning_budget"],
                timeout=step.get("timeout"),
                read_only=True,
            )

            returncode, stdout_str, stderr_str = await host.run_command_and_stream(command, cwd=project_dir)

            if returncode != 0:
                error_msg = f"❌ <b>PR review failed.</b>\n\n"
                if stderr_str.strip():
                    error_msg += f"<b>Stderr:</b>\n<pre>{html.escape(stderr_str[:800])}</pre>\n\n"
                if stdout_str.strip():
                    error_msg += f"<b>Stdout:</b>\n<pre>{html.escape(stdout_str[:800])}</pre>"
                await update.message.reply_text(error_msg, parse_mode="HTML")
                return

            review_text = stdout_str.strip()
            if not review_text:
                await update.message.reply_text("❌ PR review returned no output.")
                return

            await host._send_review_text(update, review_text)

        except asyncio.CancelledError:
            await update.message.reply_text(
                "🛑 <b>PR review stopped.</b>",
                parse_mode="HTML",
            )
            raise
        except Exception as e:
            await update.message.reply_text(f"❌ PR review error: {html.escape(str(e))}", parse_mode="HTML")
        finally:
            tasks.release(chat_id, current_task)
