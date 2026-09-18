"""Telegram bot composition root.

Pipeline, git, process, and parsing logic live in `orchestrator/`. This module
wires those collaborators together and exposes the public names tests and the
entrypoint import.
"""

from __future__ import annotations

import asyncio
import html
import os
import sys

from telegram import Update, BotCommand
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    Application,
)

from agents import (
    AgentRegistry,
    DEFAULT_AGENT_TOOL,
    MODE_EASY,
    MODE_HARD,
    resolve_pipeline_config,
    resolve_review_pipeline_config,
)
from agents.config import AGENT_INTENT_TIMEOUT
from agents.tool_specs import get_tool_spec
from orchestrator.env import sanitize_environment
from orchestrator.github import (
    _gh_auth_token as _gh_auth_token_impl,
    _ssh_github_available as _ssh_github_available_impl,
    resolve_clone_url as _resolve_clone_url_impl,
)
from orchestrator.git_reports import get_git_changes, get_pytest_summary, get_pr_url
from orchestrator.markdown import (
    inline_markdown_to_html as _inline_markdown_to_html,
    render_markdown_messages,
    split_markdown_blocks as _split_markdown_blocks,
)
from orchestrator.parsing import extract_pipeline_mode, parse_demand, parse_pr_reference
from orchestrator.paths import AGY_SCRATCH_DIR as _DEFAULT_AGY_SCRATCH_DIR
from orchestrator.paths import SESSION_FILE_PATH
from orchestrator.pipeline import execute_pipeline
from orchestrator.pr_context import fetch_pr_context
from orchestrator.pr_context import send_review_text as _send_review_text
from orchestrator.process import (
    communicate_or_cancel as _communicate_or_cancel,
    run_command_and_stream,
    terminate_process_tree as _terminate_process_tree,
    wait_or_cancel as _wait_or_cancel,
)
from orchestrator.quota import (
    capture_agy_quota_output,
    format_model_quota_section,
    parse_model_quota,
    strip_ansi as _strip_ansi,
)
from orchestrator.review import execute_pr_review
from orchestrator.session import clear_session, delete_session, load_session, save_session
from orchestrator.urls import extract_owner_repo, normalize_repo_url

sanitize_environment()

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
ALLOWED_CHAT_ID = str(TELEGRAM_CHAT_ID) if TELEGRAM_CHAT_ID else None
AGY_SCRATCH_DIR = _DEFAULT_AGY_SCRATCH_DIR
AGY_QUOTA_TIMEOUT = int(os.environ.get("AGY_QUOTA_TIMEOUT", "45"))
ACTIVE_TASKS = {}
PIPELINE_BUSY_MSG = (
    "⚠️ A pipeline is already running. Send <code>/stop</code> first, then try again."
)


async def _gh_auth_token() -> str | None:
    return await _gh_auth_token_impl()


async def _ssh_github_available() -> bool:
    return await _ssh_github_available_impl()


async def resolve_clone_url(repo_url: str, github_token: str | None) -> tuple[str | None, str, str | None]:
    return await _resolve_clone_url_impl(
        repo_url,
        github_token,
        gh_token_fn=_gh_auth_token,
        ssh_available_fn=_ssh_github_available,
    )


def fetch_agy_quota_output(timeout: int = AGY_QUOTA_TIMEOUT) -> str:
    """Runs the agy TUI /usage command via PTY and returns the captured terminal output."""
    return capture_agy_quota_output(timeout=timeout, scratch_dir=AGY_SCRATCH_DIR)


def get_model_quota_summary() -> str:
    """Fetches quota usage when the active tool supports it."""
    if not get_tool_spec(DEFAULT_AGENT_TOOL).supports_quota:
        return ""
    try:
        output = fetch_agy_quota_output()
        quota_data = parse_model_quota(output)
        if not quota_data:
            return ""
        return format_model_quota_section(quota_data)
    except Exception as e:
        print(f"Error fetching model quota: {e}", flush=True)
        return ""


async def classify_intent(message_text: str) -> str:
    """Classifies user messages using the active agent CLI, with keyword fallback."""
    prompt = f"""Classify the user intent for a coding assistant bot.
User message: "{message_text}"

Intents:
- RESUME: The user wants to continue, resume, retry, or finish the last run, or fix the error and try again.
- QUERY_STATUS: The user is asking what was done, what is the status of the last task, or what the agent remembers.
- NEW_DEMAND: The user is requesting a new software engineering task or feature.

Respond with ONLY the classification label (RESUME, QUERY_STATUS, or NEW_DEMAND) in plain text, with no markdown, punctuation, or extra words.
"""
    try:
        agent_cli = AgentRegistry.get_agent(DEFAULT_AGENT_TOOL)
        cmd = agent_cli.build_command(
            prompt,
            "gemini-3.7-flash",
            "low",
            timeout=AGENT_INTENT_TIMEOUT,
        )
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode == 0:
            result = stdout.decode('utf-8').strip().upper()
            for label in ["RESUME", "QUERY_STATUS", "NEW_DEMAND"]:
                if label in result:
                    return label
    except Exception:
        pass

    # Fallback to simple regex/keyword heuristics if the agent call fails
    cleaned = message_text.lower().strip()
    if any(k in cleaned for k in ["continue", "resume", "continuar", "recomecar", "retry", "tentar de novo"]):
        return "RESUME"
    if any(k in cleaned for k in ["status", "memory", "last", "ultima", "o que foi feito", "memoria", "lembra"]):
        return "QUERY_STATUS"

    return "NEW_DEMAND"


def _is_pipeline_active(chat_id: str) -> bool:
    task = ACTIVE_TASKS.get(chat_id)
    return task is not None and not task.done()


async def _reject_if_pipeline_active(update: Update) -> bool:
    """Returns True when a pipeline is already running and the request was rejected."""
    chat_id = str(update.effective_chat.id)
    if _is_pipeline_active(chat_id):
        await update.message.reply_text(PIPELINE_BUSY_MSG, parse_mode="HTML")
        return True
    return False


async def run_pipeline(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    repo_url: str,
    demand: str,
    mode: str = MODE_EASY,
    is_resume: bool = False,
):
    return await execute_pipeline(
        update, context, repo_url, demand, mode, is_resume, sys.modules[__name__]
    )


async def run_pr_review(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    repo_url: str,
    pr_number: int,
):
    return await execute_pr_review(update, context, repo_url, pr_number, sys.modules[__name__])


async def handle_demand(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    if chat_id != ALLOWED_CHAT_ID:
        return

    raw_demand = update.message.text

    # Classify intent using Gemini CLI or keyword fallbacks
    intent = await classify_intent(raw_demand)

    if intent == "RESUME":
        if await _reject_if_pipeline_active(update):
            return
        await run_pipeline(update, context, None, None, is_resume=True)
    elif intent == "QUERY_STATUS":
        await send_status(update)
    else:
        # NEW_DEMAND
        default_repo = os.environ.get("DEFAULT_REPO")
        session = load_session()
        last_repo = session.get("repo_url") if session else None
        clean_raw, mode = extract_pipeline_mode(raw_demand)
        repo_url, demand = parse_demand(clean_raw, default_repo, last_repo)

        # Also check demand itself in case format was repo: [hard] demand
        demand, demand_mode = extract_pipeline_mode(demand)
        if mode == MODE_EASY and demand_mode == MODE_HARD:
            mode = MODE_HARD

        if not repo_url:
            await update.message.reply_text(
                "❌ Error: No repository specified. Please prefix your demand with your repository (e.g. `owner/repo: my demand`) or configure `DEFAULT_REPO` in .env."
            )
            return

        if await _reject_if_pipeline_active(update):
            return

        await run_pipeline(update, context, repo_url, demand, mode=mode, is_resume=False)


async def handle_continue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    if chat_id != ALLOWED_CHAT_ID:
        return
    if await _reject_if_pipeline_active(update):
        return
    await run_pipeline(update, context, None, None, is_resume=True)


async def handle_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    if chat_id != ALLOWED_CHAT_ID:
        return
    await send_status(update)


async def handle_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    if chat_id != ALLOWED_CHAT_ID:
        return
    task = ACTIVE_TASKS.get(chat_id)
    if task and not task.done():
        task.cancel()
        await update.message.reply_text("🛑 Request to stop the pipeline sent.")
    else:
        await update.message.reply_text("ℹ️ No running pipeline to stop.")


async def handle_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    if chat_id != ALLOWED_CHAT_ID:
        return
    delete_session()
    await update.message.reply_text("🧹 Session memory cleared successfully.")


async def handle_review(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    if chat_id != ALLOWED_CHAT_ID:
        return

    default_repo = os.environ.get("DEFAULT_REPO")
    repo_url, pr_number = parse_pr_reference(update.message.text or "", default_repo)

    if not repo_url or pr_number is None:
        await update.message.reply_text(
            "❌ Usage: <code>/review owner/repo#123</code>\n"
            "Formats: <code>owner/repo#123</code>, <code>owner/repo:123</code>, "
            "<code>https://github.com/owner/repo/pull/123</code>, or <code>/review 123</code> with DEFAULT_REPO set.",
            parse_mode="HTML",
        )
        return

    if await _reject_if_pipeline_active(update):
        return

    await run_pr_review(update, context, repo_url, pr_number)


async def send_status(update: Update):
    session = load_session()
    if not session:
        await update.message.reply_text("ℹ️ No active session in memory.")
        return

    if "demand" not in session:
        repo_url = session.get("repo_url")
        quota_section = await asyncio.to_thread(get_model_quota_summary)
        if repo_url:
            status_msg = (
                f"ℹ️ No active session in memory.\n"
                f"📦 <b>Remembered Repository:</b> <code>{repo_url}</code>"
            )
            if quota_section:
                status_msg += f"\n\n{quota_section.rstrip()}"
            await update.message.reply_text(status_msg, parse_mode="HTML")
        else:
            if quota_section:
                await update.message.reply_text(quota_section.rstrip(), parse_mode="HTML")
            else:
                await update.message.reply_text("ℹ️ No active session in memory.")
        return

    quota_section = await asyncio.to_thread(get_model_quota_summary)
    mode = session.get("mode", MODE_EASY)
    label = "Hard (Thorough Review)" if mode == MODE_HARD else "Easy (Fast)"

    status_msg = (
        f"🧠 <b>Aegis Session Memory:</b>\n\n"
        f"📦 <b>Repository:</b> <code>{session.get('repo_url', 'N/A')}</code>\n"
        f"⚙️ <b>Mode:</b> <code>{label}</code>\n"
        f"💡 <b>Demand:</b> <code>{html.escape(session.get('demand', 'N/A'))}</code>\n"
        f"🌿 <b>Branch:</b> <code>{session.get('git_branch', 'N/A')}</code>\n"
        f"🏁 <b>Last Completed:</b> <code>{session.get('last_completed_step', 'N/A')}</code>\n\n"
    )
    if quota_section:
        status_msg += quota_section
    status_msg += "📊 <b>Step Statuses:</b>\n"
    pipeline_config = resolve_pipeline_config(mode=mode)
    for step in pipeline_config:
        step_name = step["step_name"]
        status = session.get("steps_status", {}).get(step_name, "pending")
        icon = "✅" if status == "success" else "🚫" if status == "aborted" else "❌" if status == "failed" else "⏳"
        status_msg += f"{icon} {step_name}: <code>{status}</code>\n"

    await update.message.reply_text(status_msg, parse_mode="HTML")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) == ALLOWED_CHAT_ID:
        start_message = (
            "🤖 <b>Aegis Multi-Agent System Online</b>\n\n"
            "Send your demand with the desired execution mode:\n\n"
            "⚡ <b>Easy / Standard Mode</b> (Default — faster, skips Architect Reviewer, medium review reasoning):\n"
            "• <code>owner/repo: your demand</code>\n"
            "• <code>[easy] owner/repo: your demand</code>\n\n"
            "🛡️ <b>Hard / Complex Mode</b> (Thorough — includes Architect Reviewer validation & high review reasoning):\n"
            "• <code>[hard] owner/repo: your demand</code>\n"
            "• <code>owner/repo: [hard] your demand</code>\n"
            "• <code>owner/repo: difícil: your demand</code>\n\n"
            "<b>Available Commands:</b>\n"
            "• <code>/continue</code> - Resume paused/failed pipeline\n"
            "• <code>/status</code> - Check active task and quota status\n"
            "• <code>/stop</code> - Cancel currently running pipeline\n"
            "• <code>/clear</code> - Clear active session memory\n"
            "• <code>/review owner/repo#123</code> - Review an existing GitHub PR"
        )
        await update.message.reply_text(start_message, parse_mode="HTML")


async def post_init(application: Application) -> None:
    """Registers slash commands in the Telegram client UI."""
    await application.bot.set_my_commands([
        BotCommand("start", "Start the bot and get instructions"),
        BotCommand("continue", "Resume the last paused/failed pipeline step"),
        BotCommand("status", "Query current pipeline status and memory"),
        BotCommand("stop", "Stop the current running pipeline"),
        BotCommand("clear", "Clear active session memory"),
        BotCommand("review", "Review an existing GitHub PR"),
    ])


def build_application() -> Application:
    """Builds and returns the Application instance with registered handlers and post_init."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN is not defined in environment variables.")

    # concurrent_updates(True) is required so that commands like /stop are
    # processed while a long-running pipeline is still executing. Without it,
    # python-telegram-bot handles updates sequentially and /stop would be queued
    # behind the running pipeline, never firing task.cancel() mid-run.
    app = ApplicationBuilder().token(token).concurrent_updates(True).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("continue", handle_continue))
    app.add_handler(CommandHandler("status", handle_status))
    app.add_handler(CommandHandler("stop", handle_stop))
    app.add_handler(CommandHandler("clear", handle_clear))
    app.add_handler(CommandHandler("review", handle_review))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_demand))
    return app


if __name__ == '__main__':  # pragma: no cover
    # Verify that required tokens are set in environment
    if not TOKEN or not ALLOWED_CHAT_ID:
        print("Error: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not defined in environment variables.")
        exit(1)

    app = build_application()
    app.run_polling()
