"""Telegram bot composition root.

Pipeline, git, process, and parsing behavior live on objects in `orchestrator/`.
This module wires those objects together and exposes the public names tests and
the entrypoint import.
"""

from __future__ import annotations

import os
import sys

from agents import (
    AgentRegistry,
    DEFAULT_AGENT_TOOL,
    MODE_EASY,
    MODE_HARD,
    resolve_pipeline_config,
    resolve_review_pipeline_config,
)
from agents.tool_specs import get_tool_spec
from orchestrator.bot import BotController
from orchestrator.env import environment
from orchestrator.github import github_auth
from orchestrator.git_reports import git_reports
from orchestrator.intent import intent_classifier
from orchestrator.markdown import markdown_renderer
from orchestrator.parsing import demand_parser
from orchestrator.paths import AGY_SCRATCH_DIR as _DEFAULT_AGY_SCRATCH_DIR
from orchestrator.pipeline import PipelineRunner
from orchestrator.pr_context import pull_requests
from orchestrator.process import processes
from orchestrator.quota import quota_monitor
from orchestrator.review import ReviewRunner
from orchestrator.session import load_session as _load_session
from orchestrator.session import session_store
from orchestrator.urls import repo_urls
from orchestrator.workspace import git_workspace

sanitize_environment = environment.sanitize
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

normalize_repo_url = repo_urls.normalize
extract_owner_repo = repo_urls.owner_repo
parse_demand = demand_parser.parse
extract_pipeline_mode = demand_parser.extract_mode
parse_pr_reference = demand_parser.parse_pr_reference

save_session = session_store.save
load_session = _load_session
clear_session = session_store.clear
delete_session = session_store.delete

get_git_changes = git_reports.changes
get_pytest_summary = git_reports.pytest_summary
get_pr_url = git_reports.pr_url

_inline_markdown_to_html = markdown_renderer.inline_to_html
_split_markdown_blocks = markdown_renderer.split_blocks
render_markdown_messages = markdown_renderer.render

_strip_ansi = quota_monitor.strip_ansi
parse_model_quota = quota_monitor.parse
format_model_quota_section = quota_monitor.format_section

fetch_pr_context = pull_requests.fetch
_send_review_text = pull_requests.send

_terminate_process_tree = processes.terminate
_wait_or_cancel = processes.wait_or_cancel
_communicate_or_cancel = processes.communicate_or_cancel
run_command_and_stream = processes.run_and_stream

_pipeline = PipelineRunner(git_workspace)
_review = ReviewRunner(git_workspace)


async def _gh_auth_token() -> str | None:
    return await github_auth.token()


async def _ssh_github_available() -> bool:
    return await github_auth.ssh_available()


async def resolve_clone_url(repo_url: str, github_token: str | None) -> tuple[str | None, str, str | None]:
    return await github_auth.resolve_clone_url(
        repo_url,
        github_token,
        gh_token_fn=_gh_auth_token,
        ssh_available_fn=_ssh_github_available,
    )


def fetch_agy_quota_output(timeout: int = AGY_QUOTA_TIMEOUT) -> str:
    """Runs the agy TUI /usage command via PTY and returns the captured terminal output."""
    return quota_monitor.capture(timeout=timeout, scratch_dir=AGY_SCRATCH_DIR)


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
    return await intent_classifier.classify(message_text, tool=DEFAULT_AGENT_TOOL)


async def run_pipeline(
    update,
    context,
    repo_url: str,
    demand: str,
    mode: str = MODE_EASY,
    is_resume: bool = False,
):
    return await _pipeline.execute(
        update, context, repo_url, demand, mode, is_resume, sys.modules[__name__]
    )


async def run_pr_review(update, context, repo_url: str, pr_number: int):
    return await _review.execute(update, context, repo_url, pr_number, sys.modules[__name__])


_bot = BotController(sys.modules[__name__])
handle_demand = _bot.handle_demand
handle_continue = _bot.handle_continue
handle_status = _bot.handle_status
handle_stop = _bot.handle_stop
handle_clear = _bot.handle_clear
handle_review = _bot.handle_review
send_status = _bot.send_status
start = _bot.start
post_init = _bot.post_init
build_application = _bot.build_application


if __name__ == '__main__':  # pragma: no cover
    # Verify that required tokens are set in environment
    if not TOKEN or not ALLOWED_CHAT_ID:
        print("Error: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not defined in environment variables.")
        exit(1)

    app = build_application()
    app.run_polling()
