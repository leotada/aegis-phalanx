"""PR review runner. Collaborators are resolved from the composition-root namespace."""

from __future__ import annotations

import asyncio
import html
import os

from orchestrator.paths import PROJECT_DIR
from orchestrator.workspace import clone_repository, remove_directory


async def _checkout_pr(repo_owner_name: str, pr_number: int, project_dir: str, ns) -> tuple[int, bytes]:
    checkout_proc = await asyncio.create_subprocess_exec(
        "gh", "pr", "checkout", str(pr_number), "--repo", repo_owner_name,
        cwd=project_dir,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    _, checkout_err = await ns._communicate_or_cancel(checkout_proc)
    return checkout_proc.returncode or 0, checkout_err


async def execute_pr_review(update, context, repo_url: str, pr_number: int, ns) -> None:
    """Clones a repo, runs a single PR review step, and returns only the review text."""
    chat_id = str(update.effective_chat.id)
    current_task = asyncio.current_task()
    ns.ACTIVE_TASKS[chat_id] = current_task

    project_dir = PROJECT_DIR
    repo_owner_name = ns.extract_owner_repo(repo_url) or repo_url
    github_token = os.environ.get("GITHUB_TOKEN")
    review_config = ns.resolve_review_pipeline_config()
    step = review_config[0]

    try:
        auth_repo_url, _auth_method, auth_error = await ns.resolve_clone_url(repo_url, github_token)
        if auth_error:
            await update.message.reply_text(f"❌ Error: {auth_error}", parse_mode="HTML")
            return

        if os.path.exists(project_dir):
            await remove_directory(
                project_dir,
                start_new_session=True,
                wait_fn=ns._wait_or_cancel,
            )

        returncode, _stdout_c, stderr_c = await clone_repository(
            auth_repo_url,
            project_dir,
            start_new_session=True,
            communicate_fn=ns._communicate_or_cancel,
        )
        if returncode != 0:
            err = stderr_c.decode("utf-8", errors="replace")[:800]
            await update.message.reply_text(
                f"❌ <b>Failed to clone repository.</b>\n<b>Stderr:</b>\n<pre>{html.escape(err)}</pre>",
                parse_mode="HTML",
            )
            return

        checkout_code, checkout_err = await _checkout_pr(repo_owner_name, pr_number, project_dir, ns)
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
            pr_context=await ns.fetch_pr_context(repo_owner_name, pr_number, project_dir),
        )

        agent_cli = ns.AgentRegistry.get_agent(step["tool"])
        command = agent_cli.build_command(
            prompt=prompt_content,
            model=step["model"],
            reasoning_budget=step["reasoning_budget"],
            timeout=step.get("timeout"),
            read_only=True,
        )

        returncode, stdout_str, stderr_str = await ns.run_command_and_stream(command, cwd=project_dir)

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

        await ns._send_review_text(update, review_text)

    except asyncio.CancelledError:
        await update.message.reply_text(
            "🛑 <b>PR review stopped.</b>",
            parse_mode="HTML",
        )
        raise
    except Exception as e:
        await update.message.reply_text(f"❌ PR review error: {html.escape(str(e))}", parse_mode="HTML")
    finally:
        if ns.ACTIVE_TASKS.get(chat_id) == current_task:
            ns.ACTIVE_TASKS.pop(chat_id, None)
