"""TDD pipeline runner. Collaborators are resolved from the composition-root namespace."""

from __future__ import annotations

import asyncio
import html
import os

from orchestrator.memory_hooks import PipelineMemory
from orchestrator.paths import PROJECT_DIR
from orchestrator.pipeline_steps import (
    branch_name_from_demand,
    execute_pipeline_step,
    last_completed_step_name,
    mode_label,
)
from orchestrator.workspace import (
    checkout_branch,
    checkout_origin_branch,
    clone_repository,
    configure_git_identity,
    create_branch,
    local_branch_exists,
    remove_directory,
)


async def _load_or_start_session(update, repo_url, demand, mode, is_resume, ns):
    session_data = ns.load_session()
    steps_status = {}
    git_branch = ""

    peeked_step_name = None
    if is_resume:
        if not session_data:
            await update.message.reply_text("❌ Error: No previous session found to resume.")
            return None
        repo_url = session_data["repo_url"]
        demand = session_data["demand"]
        mode = session_data.get("mode", ns.MODE_EASY)
        git_branch = session_data["git_branch"]
        steps_status = session_data.get("steps_status", {})
        pipeline_config = ns.resolve_pipeline_config(mode=mode)

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
            f"⚙️ <b>Mode:</b> <code>{mode_label(mode, hard_mode=ns.MODE_HARD)}</code>\n"
            f"💡 <b>Demand:</b> <code>{html.escape(demand)}</code>\n"
            f"⏳ <b>Resuming from step:</b> <code>{pipeline_config[start_index]['step_name']}</code>",
            parse_mode="HTML",
        )
    else:
        ns.clear_session()
        start_index = 0
        pipeline_config = ns.resolve_pipeline_config(mode=mode)
        git_branch = branch_name_from_demand(demand)
        await update.message.reply_text(
            f"🚀 <b>Starting Multi-Model TDD Pipeline</b>\n"
            f"📦 <b>Repository:</b> <code>{repo_url}</code>\n"
            f"⚙️ <b>Mode:</b> <code>{mode_label(mode, hard_mode=ns.MODE_HARD)}</code>\n"
            f"💡 <b>Demand:</b> <code>{html.escape(demand)}</code>",
            parse_mode="HTML",
        )

    return repo_url, demand, mode, git_branch, steps_status, pipeline_config, start_index, peeked_step_name


async def _prepare_workspace(update, *, repo_url, github_token, git_branch, is_resume, start_index, ns):
    auth_repo_url, _auth_method, auth_error = await ns.resolve_clone_url(repo_url, github_token)
    if auth_error:
        await update.message.reply_text(f"❌ Error: {auth_error}", parse_mode="HTML")
        return None

    project_dir = PROJECT_DIR
    try:
        if not is_resume or not os.path.exists(project_dir):
            if os.path.exists(project_dir):
                await remove_directory(project_dir)

            await update.message.reply_text("📥 Cloning repository...")
            returncode, _stdout_c, stderr_c = await clone_repository(auth_repo_url, project_dir)
            if returncode != 0:
                err = stderr_c.decode('utf-8', errors='replace')[:800]
                await update.message.reply_text(
                    f"❌ <b>Failed to clone repository.</b>\n<b>Stderr:</b>\n<pre>{html.escape(err)}</pre>",
                    parse_mode="HTML",
                )
                return None

            await configure_git_identity(project_dir)

        if is_resume:
            if await local_branch_exists(git_branch, project_dir):
                await checkout_branch(git_branch, project_dir)
            else:
                if await checkout_origin_branch(git_branch, project_dir) != 0:
                    await update.message.reply_text(
                        f"⚠️ <b>Warning:</b> The local branch <code>{git_branch}</code> and its commits were lost because the container was rebuilt or the directory was cleaned.\n"
                        "Cannot resume. Restarting the pipeline from the beginning...",
                        parse_mode="HTML",
                    )
                    start_index = 0
                    is_resume = False
                    await create_branch(git_branch, project_dir)
        else:
            await create_branch(git_branch, project_dir)
    except Exception as e:
        await update.message.reply_text(f"❌ Initialization error: {str(e)}")
        return None

    return project_dir, is_resume, start_index


async def _ensure_pull_request(update, repo_url, project_dir, ns) -> str:
    final_pr_url = ns.get_pr_url()
    if final_pr_url:
        return final_pr_url

    repo_owner_name = ns.extract_owner_repo(repo_url) or repo_url
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
            return ns.get_pr_url()
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
    return ns.get_pr_url()


async def execute_pipeline(update, context, repo_url: str, demand: str, mode: str, is_resume: bool, ns) -> None:
    chat_id = str(update.effective_chat.id)
    current_task = asyncio.current_task()
    ns.ACTIVE_TASKS[chat_id] = current_task

    step_name = None
    idx = None
    pipeline_config = []
    steps_status = {}
    git_branch = ""
    memory = PipelineMemory(ns.get_memory_manager())
    try:
        github_token = os.environ.get("GITHUB_TOKEN")
        session = await _load_or_start_session(update, repo_url, demand, mode, is_resume, ns)
        if session is None:
            return
        repo_url, demand, mode, git_branch, steps_status, pipeline_config, start_index, step_name = session

        prepared = await _prepare_workspace(
            update,
            repo_url=repo_url,
            github_token=github_token,
            git_branch=git_branch,
            is_resume=is_resume,
            start_index=start_index,
            ns=ns,
        )
        if prepared is None:
            return
        project_dir, is_resume, start_index = prepared

        await memory.begin(
            cwd=project_dir,
            project=ns.extract_owner_repo(repo_url) or repo_url,
            demand=demand,
            git_branch=git_branch,
            is_resume=is_resume,
        )

        for idx in range(start_index, len(pipeline_config)):
            step = pipeline_config[idx]
            step_name = step["step_name"]
            status = await execute_pipeline_step(
                update,
                step,
                idx,
                demand=demand,
                repo_url=repo_url,
                git_branch=git_branch,
                mode=mode,
                steps_status=steps_status,
                pipeline_config=pipeline_config,
                memory=memory,
                ns=ns,
                project_dir=project_dir,
            )
            if status != "success":
                return

        final_pr_url = await _ensure_pull_request(update, repo_url, project_dir, ns)
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
        await memory.finish("success")
        ns.clear_session()
    except asyncio.CancelledError:
        if step_name:
            steps_status[step_name] = "failed"
            last_completed = last_completed_step_name(idx, step_name, pipeline_config)
            ns.save_session(repo_url, demand, last_completed, steps_status, git_branch, mode=mode)
            await memory.fail(
                step_name=step_name,
                status="stopped",
                git_changes=ns.get_git_changes(),
                stdout="",
            )
            await update.message.reply_text(
                f"🛑 <b>Pipeline stopped in step:</b> <code>{step_name}</code>\n"
                "You can resume later with <code>/continue</code>.",
                parse_mode="HTML",
            )
        else:
            await memory.finish("stopped")
            await update.message.reply_text("🛑 Pipeline stopped during initialization.")
        raise
    finally:
        if ns.ACTIVE_TASKS.get(chat_id) == current_task:
            ns.ACTIVE_TASKS.pop(chat_id, None)
