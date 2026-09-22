"""TDD pipeline runner. Collaborators are resolved from the composition-root host."""

from __future__ import annotations

import asyncio
import html
import os

from orchestrator.pipeline_steps import PipelineStepExecutor
from orchestrator.tasks import ActiveTasks
from orchestrator.workspace import GitWorkspace, git_workspace


class PipelineRunner:
    """Clones a repository and walks the TDD pipeline, resuming from the saved session."""

    def __init__(self, workspace: GitWorkspace | None = None, steps: PipelineStepExecutor | None = None):
        self.workspace = workspace or git_workspace
        self.steps = steps or PipelineStepExecutor(self.workspace)

    async def _load_or_start_session(self, update, repo_url, demand, mode, is_resume, host):
        session_data = host.load_session()
        steps_status = {}
        git_branch = ""

        peeked_step_name = None
        if is_resume:
            if not session_data:
                await update.message.reply_text("❌ Error: No previous session found to resume.")
                return None
            repo_url = session_data["repo_url"]
            demand = session_data["demand"]
            mode = session_data.get("mode", host.MODE_EASY)
            git_branch = session_data["git_branch"]
            steps_status = session_data.get("steps_status", {})
            pipeline_config = host.resolve_pipeline_config(mode=mode)

            start_index = 0
            for i, step in enumerate(pipeline_config):
                peeked_step_name = step["step_name"]
                if steps_status.get(peeked_step_name) != "success":
                    start_index = i
                    break
            else:
                await update.message.reply_text("✅ All steps in the last pipeline were already completed successfully!")
                return None

            await update.message.reply_text(
                f"🔄 <b>Resuming pipeline for:</b>\n"
                f"📦 <b>Repository:</b> <code>{repo_url}</code>\n"
                f"⚙️ <b>Mode:</b> <code>{self.steps.mode_label(mode, hard_mode=host.MODE_HARD)}</code>\n"
                f"💡 <b>Demand:</b> <code>{html.escape(demand)}</code>\n"
                f"⏳ <b>Resuming from step:</b> <code>{pipeline_config[start_index]['step_name']}</code>",
                parse_mode="HTML",
            )
        else:
            host.clear_session()
            start_index = 0
            pipeline_config = host.resolve_pipeline_config(mode=mode)
            git_branch = self.steps.branch_name(demand)
            await update.message.reply_text(
                f"🚀 <b>Starting Multi-Model TDD Pipeline</b>\n"
                f"📦 <b>Repository:</b> <code>{repo_url}</code>\n"
                f"⚙️ <b>Mode:</b> <code>{self.steps.mode_label(mode, hard_mode=host.MODE_HARD)}</code>\n"
                f"💡 <b>Demand:</b> <code>{html.escape(demand)}</code>",
                parse_mode="HTML",
            )

        return repo_url, demand, mode, git_branch, steps_status, pipeline_config, start_index, peeked_step_name

    async def _prepare_workspace(self, update, *, repo_url, github_token, git_branch, is_resume, start_index, host):
        auth_repo_url, _auth_method, auth_error = await host.resolve_clone_url(repo_url, github_token)
        if auth_error:
            await update.message.reply_text(f"❌ Error: {auth_error}", parse_mode="HTML")
            return None

        project_dir = self.workspace.project_dir
        try:
            if not is_resume or not os.path.exists(project_dir):
                if os.path.exists(project_dir):
                    await self.workspace.remove(project_dir)

                await update.message.reply_text("📥 Cloning repository...")
                returncode, _stdout_c, stderr_c = await self.workspace.clone(auth_repo_url, project_dir)
                if returncode != 0:
                    err = stderr_c.decode('utf-8', errors='replace')[:800]
                    await update.message.reply_text(
                        f"❌ <b>Failed to clone repository.</b>\n<b>Stderr:</b>\n<pre>{html.escape(err)}</pre>",
                        parse_mode="HTML",
                    )
                    return None

                await self.workspace.configure_identity(project_dir)

            if is_resume:
                if await self.workspace.local_branch_exists(git_branch, project_dir):
                    await self.workspace.checkout(git_branch, project_dir)
                else:
                    if await self.workspace.checkout_origin(git_branch, project_dir) != 0:
                        await update.message.reply_text(
                            f"⚠️ <b>Warning:</b> The local branch <code>{git_branch}</code> and its commits were lost because the container was rebuilt or the directory was cleaned.\n"
                            "Cannot resume. Restarting the pipeline from the beginning...",
                            parse_mode="HTML",
                        )
                        start_index = 0
                        is_resume = False
                        await self.workspace.create_branch(git_branch, project_dir)
            else:
                await self.workspace.create_branch(git_branch, project_dir)
        except Exception as e:
            await update.message.reply_text(f"❌ Initialization error: {str(e)}")
            return None

        return project_dir, is_resume, start_index

    async def _ensure_pull_request(self, update, repo_url, project_dir, host) -> str:
        final_pr_url = host.get_pr_url()
        if final_pr_url:
            return final_pr_url

        repo_owner_name = host.extract_owner_repo(repo_url) or repo_url
        await update.message.reply_text("⏳ <b>Creating Pull Request...</b>", parse_mode="HTML")
        try:
            proc = await asyncio.create_subprocess_exec(
                "gh", "pr", "create", "--fill", "--repo", repo_owner_name,
                cwd=project_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _stdout_pr, stderr_pr = await proc.communicate()
            if proc.returncode == 0:
                return host.get_pr_url()
            err_msg = stderr_pr.decode('utf-8', errors='replace').strip()
            await update.message.reply_text(
                f"⚠️ <b>Failed to create PR via CLI:</b>\n<pre>{html.escape(err_msg[:800])}</pre>",
                parse_mode="HTML",
            )
        except Exception as e:
            await update.message.reply_text(
                f"⚠️ <b>Error creating PR:</b> <code>{html.escape(str(e))}</code>",
                parse_mode="HTML",
            )
        return host.get_pr_url()

    async def execute(self, update, context, repo_url: str, demand: str, mode: str, is_resume: bool, host) -> None:
        chat_id = str(update.effective_chat.id)
        current_task = asyncio.current_task()
        tasks = ActiveTasks(host.ACTIVE_TASKS)
        tasks.track(chat_id, current_task)

        step_name = None
        idx = None
        pipeline_config = []
        steps_status = {}
        git_branch = ""
        try:
            github_token = os.environ.get("GITHUB_TOKEN")
            session = await self._load_or_start_session(update, repo_url, demand, mode, is_resume, host)
            if session is None:
                return
            repo_url, demand, mode, git_branch, steps_status, pipeline_config, start_index, step_name = session

            prepared = await self._prepare_workspace(
                update,
                repo_url=repo_url,
                github_token=github_token,
                git_branch=git_branch,
                is_resume=is_resume,
                start_index=start_index,
                host=host,
            )
            if prepared is None:
                return
            project_dir, is_resume, start_index = prepared

            for idx in range(start_index, len(pipeline_config)):
                step = pipeline_config[idx]
                step_name = step["step_name"]
                status = await self.steps.execute(
                    update,
                    step,
                    idx,
                    demand=demand,
                    repo_url=repo_url,
                    git_branch=git_branch,
                    mode=mode,
                    steps_status=steps_status,
                    pipeline_config=pipeline_config,
                    host=host,
                    project_dir=project_dir,
                )
                if status != "success":
                    return

            final_pr_url = await self._ensure_pull_request(update, repo_url, project_dir, host)
            if final_pr_url:
                await update.message.reply_text(
                    f"✅ <b>Multi-Model Pipeline completed successfully!</b>\n\n"
                    f"🔗 <b>PR Opened:</b> <a href=\"{final_pr_url}\">{final_pr_url}</a>",
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
            else:
                await update.message.reply_text(
                    "✅ <b>Multi-Model Pipeline completed!</b>\n\n"
                    "⚠️ Could not confirm PR URL — check the repository manually or use <code>/status</code> to review completed steps.",
                    parse_mode="HTML",
                )
            host.clear_session()
        except asyncio.CancelledError:
            if step_name:
                steps_status[step_name] = "failed"
                last_completed = self.steps.last_completed_name(idx, step_name, pipeline_config)
                host.save_session(repo_url, demand, last_completed, steps_status, git_branch, mode=mode)
                await update.message.reply_text(
                    f"🛑 <b>Pipeline stopped in step:</b> <code>{step_name}</code>\n"
                    "You can resume later with <code>/continue</code>.",
                    parse_mode="HTML",
                )
            else:
                await update.message.reply_text("🛑 Pipeline stopped during initialization.")
            raise
        finally:
            tasks.release(chat_id, current_task)
