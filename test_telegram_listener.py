import os
import pytest
import asyncio
import importlib
from agents import AgentRegistry, AntigravityAgentCLI, CursorAgentCLI
from agents.pipeline import PIPELINE_CONFIG, resolve_pipeline_config
from telegram_listener import (
    sanitize_environment,
    parse_demand,
    parse_pr_reference,
    save_session,
    load_session,
    clear_session,
    delete_session,
    classify_intent,
    extract_owner_repo,
    parse_model_quota,
    format_model_quota_section,
)

def test_antigravity_cli_timeout_argument(monkeypatch):
    # Verify default step timeout is used when no per-step timeout is given
    cli = AntigravityAgentCLI()
    cmd = cli.build_command("Test prompt", "gemini-3.5-flash", "low")
    assert "--print-timeout" in cmd
    assert "5m" in cmd

    # Verify we can override step timeout via env variable
    monkeypatch.setenv("AGENT_STEP_TIMEOUT", "10m")
    import agents.config
    import agents.adapters.agy
    importlib.reload(agents.config)
    importlib.reload(agents.adapters.agy)

    try:
        cli2 = agents.adapters.agy.AntigravityAgentCLI()
        cmd2 = cli2.build_command("Test prompt", "gemini-3.5-flash", "low")
        assert "--print-timeout" in cmd2
        assert "10m" in cmd2
    finally:
        monkeypatch.delenv("AGENT_STEP_TIMEOUT", raising=False)
        importlib.reload(agents.config)
        importlib.reload(agents.adapters.agy)


def test_antigravity_cli_per_step_timeout_override():
    """A per-step timeout passed to build_command should override the global default."""
    cli = AntigravityAgentCLI()
    cmd = cli.build_command("Test prompt", "gemini-3.5-flash", "low", timeout="20m")
    assert "--print-timeout" in cmd
    idx = cmd.index("--print-timeout")
    assert cmd[idx + 1] == "20m"


def test_cursor_cli_build_command(monkeypatch):
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    cli = CursorAgentCLI()
    cmd = cli.build_command("Test prompt", "gemini-3.1-pro", "high", timeout="15m")

    assert cmd[0] == "agent"
    assert "--print" in cmd
    assert "Test prompt" in cmd
    assert cmd.index("Test prompt") > cmd.index("--print")
    assert "--model" in cmd
    assert cmd[cmd.index("--model") + 1] == "auto"
    assert "--trust" in cmd
    assert "--force" in cmd
    assert "--mode" not in cmd
    assert "--api-key" not in cmd


def test_cursor_cli_read_only_review_command(monkeypatch):
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    cli = CursorAgentCLI()
    cmd = cli.build_command("Review prompt", "auto", "high", read_only=True)

    assert "--print" in cmd
    assert "--mode" in cmd
    assert cmd[cmd.index("--mode") + 1] == "ask"
    assert "--force" not in cmd
    assert "Review prompt" in cmd


def test_cursor_cli_always_uses_auto_model(monkeypatch):
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    cli = CursorAgentCLI()
    cmd = cli.build_command("Another prompt", "gemini-3.5-flash", "low")

    assert cmd[cmd.index("--model") + 1] == "auto"


def test_cursor_auth_api_key_fallback(monkeypatch):
    cli = CursorAgentCLI()
    monkeypatch.setenv("CURSOR_API_KEY", "cursor_test_key")
    cmd = cli.build_command("Prompt", "auto", "medium")

    assert "--api-key" in cmd
    assert cmd[cmd.index("--api-key") + 1] == "cursor_test_key"


def test_agent_registry_has_cursor():
    agent = AgentRegistry.get_agent("cursor")
    assert isinstance(agent, CursorAgentCLI)


def test_pipeline_tool_env_override(monkeypatch):
    monkeypatch.setenv("AGENT_TOOL", "cursor")
    resolved = resolve_pipeline_config()
    assert len(resolved) == len(PIPELINE_CONFIG)
    assert all(step["tool"] == "cursor" for step in resolved)


def test_extract_owner_repo_ssh():
    assert extract_owner_repo("git@github.com:leotada/visto.git") == "leotada/visto"


def test_extract_owner_repo_ssh_no_dot_git():
    assert extract_owner_repo("git@github.com:leotada/visto") == "leotada/visto"


def test_extract_owner_repo_https():
    assert extract_owner_repo("https://github.com/leotada/visto.git") == "leotada/visto"


def test_extract_owner_repo_https_no_dot_git():
    assert extract_owner_repo("https://github.com/leotada/visto") == "leotada/visto"


def test_extract_owner_repo_authenticated_https():
    # Authenticated URLs (with token) should still parse cleanly
    assert extract_owner_repo("https://x-access-token:gho_abc@github.com/leotada/visto.git") == "leotada/visto"


def test_extract_owner_repo_invalid_returns_none():
    assert extract_owner_repo("not-a-github-url") is None



def test_sanitize_environment_removes_placeholder_token():
    os.environ["GITHUB_TOKEN"] = "your_github_token_here"
    sanitize_environment()
    assert "GITHUB_TOKEN" not in os.environ

def test_sanitize_environment_retains_valid_token():
    os.environ["GITHUB_TOKEN"] = "gho_validtoken123"
    sanitize_environment()
    assert os.environ.get("GITHUB_TOKEN") == "gho_validtoken123"

def test_parse_demand_with_repo_owner_format():
    repo, clean_demand = parse_demand("leotada/visto: add SQLAlchemy entity", "default/repo")
    assert repo == "https://github.com/leotada/visto.git"
    assert clean_demand == "add SQLAlchemy entity"

def test_parse_demand_with_full_url():
    repo, clean_demand = parse_demand("https://github.com/leotada/aegis-phalanx.git: fix timeout", "default/repo")
    assert repo == "https://github.com/leotada/aegis-phalanx.git"
    assert clean_demand == "fix timeout"

def test_parse_demand_fallback_to_default():
    repo, clean_demand = parse_demand("just a description", "default/repo")
    assert repo == "https://github.com/default/repo.git"
    assert clean_demand == "just a description"

def test_parse_demand_no_default_and_no_pattern():
    repo, clean_demand = parse_demand("just a description with no default", None)
    assert repo is None
    assert clean_demand == "just a description with no default"

def test_parse_demand_fallback_to_last_repo():
    repo, clean_demand = parse_demand("just a description", None, "owner/last-repo")
    assert repo == "https://github.com/owner/last-repo.git"
    assert clean_demand == "just a description"


def test_parse_pr_reference_owner_repo_hash():
    repo, pr_number = parse_pr_reference("owner/repo#42")
    assert repo == "https://github.com/owner/repo.git"
    assert pr_number == 42


def test_parse_pr_reference_owner_repo_colon():
    repo, pr_number = parse_pr_reference("owner/repo:42")
    assert repo == "https://github.com/owner/repo.git"
    assert pr_number == 42


def test_parse_pr_reference_owner_repo_space():
    repo, pr_number = parse_pr_reference("owner/repo 42")
    assert repo == "https://github.com/owner/repo.git"
    assert pr_number == 42


def test_parse_pr_reference_github_url():
    repo, pr_number = parse_pr_reference("https://github.com/owner/repo/pull/99")
    assert repo == "https://github.com/owner/repo.git"
    assert pr_number == 99


def test_parse_pr_reference_with_review_command_prefix():
    repo, pr_number = parse_pr_reference("/review owner/repo#7")
    assert repo == "https://github.com/owner/repo.git"
    assert pr_number == 7


def test_parse_pr_reference_number_with_default_repo():
    repo, pr_number = parse_pr_reference("123", "default/repo")
    assert repo == "https://github.com/default/repo.git"
    assert pr_number == 123


def test_parse_pr_reference_hash_number_with_default_repo():
    repo, pr_number = parse_pr_reference("#456", "default/repo")
    assert repo == "https://github.com/default/repo.git"
    assert pr_number == 456


def test_parse_pr_reference_invalid_returns_none():
    repo, pr_number = parse_pr_reference("not a pr reference")
    assert repo is None
    assert pr_number is None


def test_parse_pr_reference_number_without_default_repo():
    repo, pr_number = parse_pr_reference("123")
    assert repo is None
    assert pr_number is None

def test_save_load_clear_session(tmp_path):
    session_file = tmp_path / "session.json"
    
    # Assert load on non-existing file returns default structure
    assert load_session(session_file) is None
    
    # Save a session state
    save_session(
        repo_url="https://github.com/owner/repo.git",
        demand="implement user auth",
        last_completed_step="Developer",
        steps_status={"Architect": "success", "Developer": "success", "Reviewer": "pending"},
        git_branch="feature/user-auth",
        session_file_path=session_file
    )
    
    # Load and assert contents
    session = load_session(session_file)
    assert session is not None
    assert session["repo_url"] == "https://github.com/owner/repo.git"
    assert session["demand"] == "implement user auth"
    assert session["last_completed_step"] == "Developer"
    assert session["steps_status"]["Architect"] == "success"
    assert session["git_branch"] == "feature/user-auth"
    
    # Clear session and assert it retains only the repo_url
    clear_session(session_file)
    session = load_session(session_file)
    assert session == {"repo_url": "https://github.com/owner/repo.git"}

    # Delete session completely and assert it is removed
    delete_session(session_file)
    assert load_session(session_file) is None

from unittest.mock import AsyncMock, patch

@pytest.mark.anyio
async def test_classify_intent_via_agy_success():
    mock_process = AsyncMock()
    mock_process.returncode = 0
    mock_process.communicate.return_value = (b"RESUME\n", b"")

    with patch("telegram_listener.DEFAULT_AGENT_TOOL", "agy"), \
         patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec:
        res = await classify_intent("some message")
        assert res == "RESUME"
        mock_exec.assert_called_once()
        assert mock_exec.call_args[0][0] == "agy"
        assert "Gemini 3.5 Flash (Low)" in mock_exec.call_args[0]

@pytest.mark.anyio
async def test_classify_intent_via_agy_failure_fallback():
    mock_process = AsyncMock()
    mock_process.returncode = 1
    mock_process.communicate.return_value = (b"", b"Error")
    
    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        res = await classify_intent("please resume the task")
        assert res == "RESUME"
        
        res = await classify_intent("what is the status?")
        assert res == "QUERY_STATUS"
        
        res = await classify_intent("implement a new feature in visto")
        assert res == "NEW_DEMAND"


@pytest.mark.anyio
async def test_post_init_registers_bot_commands():
    from telegram_listener import post_init
    from telegram import BotCommand
    from unittest.mock import AsyncMock, MagicMock
    
    mock_app = MagicMock()
    mock_app.bot = MagicMock()
    mock_app.bot.set_my_commands = AsyncMock()
    
    await post_init(mock_app)
    
    mock_app.bot.set_my_commands.assert_called_once()
    args, kwargs = mock_app.bot.set_my_commands.call_args
    commands = args[0]
    
    expected_commands = {
        "start": "Start the bot and get instructions",
        "continue": "Resume the last paused/failed pipeline step",
        "status": "Query current pipeline status and memory",
        "stop": "Stop the current running pipeline",
        "clear": "Clear active session memory",
        "review": "Review an existing GitHub PR",
    }
    
    assert len(commands) == len(expected_commands)
    for cmd in commands:
        assert isinstance(cmd, BotCommand)
        assert cmd.command in expected_commands
        assert cmd.description == expected_commands[cmd.command]


def test_build_application():
    from telegram_listener import build_application
    import os
    os.environ["TELEGRAM_BOT_TOKEN"] = "12345:dummy_token"
    try:
        app = build_application()
        assert app is not None
        assert app.post_init is not None
        assert app.concurrent_updates > 1
    finally:
        del os.environ["TELEGRAM_BOT_TOKEN"]


def test_parse_demand_various_formats():
    # SSH formats
    repo, clean = parse_demand("git@github.com:owner/repo.git: test demand", None)
    assert repo == "git@github.com:owner/repo.git"
    assert clean == "test demand"

    repo, clean = parse_demand("git@github.com:owner/repo: test demand", None)
    assert repo == "git@github.com:owner/repo.git"
    assert clean == "test demand"

    repo, clean = parse_demand("git@github.com:owner/repo.git test demand", None)
    assert repo == "git@github.com:owner/repo.git"
    assert clean == "test demand"

    repo, clean = parse_demand("git@github.com:owner/repo test demand", None)
    assert repo == "git@github.com:owner/repo.git"
    assert clean == "test demand"

    repo, clean = parse_demand("git@github.com:owner/repo.git", None)
    assert repo == "git@github.com:owner/repo.git"
    assert clean == ""

    # SSH URI format
    repo, clean = parse_demand("ssh://git@github.com/owner/repo.git: test demand", None)
    assert repo == "git@github.com:owner/repo.git"
    assert clean == "test demand"

    # HTTPS formats
    repo, clean = parse_demand("https://github.com/owner/repo.git: test demand", None)
    assert repo == "https://github.com/owner/repo.git"
    assert clean == "test demand"

    repo, clean = parse_demand("https://github.com/owner/repo: test demand", None)
    assert repo == "https://github.com/owner/repo.git"
    assert clean == "test demand"

    repo, clean = parse_demand("https://github.com/owner/repo.git test demand", None)
    assert repo == "https://github.com/owner/repo.git"
    assert clean == "test demand"

    repo, clean = parse_demand("https://github.com/owner/repo test demand", None)
    assert repo == "https://github.com/owner/repo.git"
    assert clean == "test demand"

    repo, clean = parse_demand("https://github.com/owner/repo.git", None)
    assert repo == "https://github.com/owner/repo.git"
    assert clean == ""

    # Shorthand formats
    repo, clean = parse_demand("owner/repo: test demand", None)
    assert repo == "https://github.com/owner/repo.git"
    assert clean == "test demand"

    repo, clean = parse_demand("owner/repo", None)
    assert repo == "https://github.com/owner/repo.git"
    assert clean == ""

    # URLs anywhere in the message (middle, end, with prepositions/connectors)
    repo, clean = parse_demand("implement user login in https://github.com/owner/repo.git", None)
    assert repo == "https://github.com/owner/repo.git"
    assert clean == "implement user login"

    repo, clean = parse_demand("caching for git@github.com:owner/repo", None)
    assert repo == "git@github.com:owner/repo.git"
    assert clean == "caching"

    repo, clean = parse_demand("create a new endpoint on https://github.com/owner/repo.git for users", None)
    assert repo == "https://github.com/owner/repo.git"
    assert clean == "create a new endpoint for users"

    repo, clean = parse_demand("https://github.com/owner/repo.git : do something", None)
    assert repo == "https://github.com/owner/repo.git"
    assert clean == "do something"


@pytest.mark.anyio
async def test_run_pipeline_ssh_no_token(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock, patch
    
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    
    mock_update = AsyncMock()
    mock_update.message = AsyncMock()
    mock_update.message.reply_text = AsyncMock()
    
    mock_context = MagicMock()
    
    mock_process = AsyncMock()
    mock_process.returncode = 1  # exit early on clone fail
    mock_process.communicate.return_value = (b"", b"dummy clone fail")
    
    from telegram_listener import run_pipeline
    
    with patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec:
        await run_pipeline(mock_update, mock_context, "git@github.com:owner/repo.git", "test demand")
        
        # Verify it didn't fail on GITHUB_TOKEN check but proceeded to clone with SSH URL
        mock_exec.assert_any_call(
            "git", "clone", "git@github.com:owner/repo.git", "/workspace/project",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )


@pytest.mark.anyio
async def test_pipeline_reports_honestly_when_no_pr_url(monkeypatch):
    """When no PR URL is found after the pipeline, the message must NOT claim 'PR opened'."""
    from unittest.mock import AsyncMock, MagicMock, patch
    import telegram_listener

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    mock_update = AsyncMock()
    mock_update.message = AsyncMock()
    mock_update.message.reply_text = AsyncMock()

    mock_context = MagicMock()

    # Simulate: clone succeeds, git config succeeds, checkout succeeds,
    # then each pipeline step exits 0 (success) but produces no output
    mock_process = AsyncMock()
    mock_process.returncode = 0
    mock_process.communicate.return_value = (b"", b"")

    with patch("asyncio.create_subprocess_exec", return_value=mock_process), \
         patch.object(telegram_listener, "get_pr_url", return_value=""), \
         patch.object(telegram_listener, "get_git_changes", return_value=""), \
         patch.object(telegram_listener, "get_pytest_summary", return_value=""), \
         patch.object(telegram_listener, "run_command_and_stream", return_value=(0, "", "")):

        await telegram_listener.run_pipeline(
            mock_update, mock_context,
            "git@github.com:owner/repo.git", "test demand"
        )

    # Gather all reply_text calls
    calls = [str(call) for call in mock_update.message.reply_text.call_args_list]
    final_call = calls[-1] if calls else ""

    # Must NOT contain the old lying message
    assert "PR opened on repository" not in final_call
    # Must contain an honest indicator
    assert "Could not confirm PR" in final_call or "manually" in final_call


def test_pipeline_config_steps():
    """Verify that PIPELINE_CONFIG has the split Architect steps, modified Code Reviewer step, and Refactoring Developer step."""
    from agents.pipeline import PIPELINE_CONFIG
    
    # Verify we have 6 steps now
    assert len(PIPELINE_CONFIG) == 6
    
    step_names = [step["step_name"] for step in PIPELINE_CONFIG]
    assert step_names[0] == "Architect (Planning - PLAN)"
    assert step_names[1] == "Test Developer (Testing - RED)"
    assert step_names[2] == "Developer (Implementation - GREEN)"
    assert step_names[3] == "Code Reviewer (Review - PLAN)"
    assert step_names[4] == "Refactoring Developer (Refactoring - REFACTOR)"
    assert step_names[5] == "GitOps (Documentation and PR)"
    
    # Verify Architect prompt contents/expectations
    architect_prompt = PIPELINE_CONFIG[0]["prompt"]
    assert "architect_plan.md" in architect_prompt
    assert "Test Specification Plan" in architect_prompt
    assert "Implementation Plan" in architect_prompt
    
    # Verify Test Developer prompt contents/expectations
    test_developer_prompt = PIPELINE_CONFIG[1]["prompt"]
    assert "architect_plan.md" in test_developer_prompt
    assert "Test Specification Plan" in test_developer_prompt
    assert "Do NOT delete" in test_developer_prompt
    
    # Verify Developer prompt contents/expectations
    developer_prompt = PIPELINE_CONFIG[2]["prompt"]
    assert "architect_plan.md" in developer_prompt
    assert "Implementation Plan" in developer_prompt
    assert "Do NOT delete" in developer_prompt

    # Verify Code Reviewer prompt contents/expectations
    reviewer_prompt = PIPELINE_CONFIG[3]["prompt"]
    assert "architect_plan.md" in reviewer_prompt
    assert "refactor_plan.md" in reviewer_prompt
    assert "Do NOT modify" in reviewer_prompt
    assert "delete the `architect_plan.md` file" in reviewer_prompt
    
    # Verify Refactoring Developer prompt contents/expectations
    refactor_developer_prompt = PIPELINE_CONFIG[4]["prompt"]
    assert "refactor_plan.md" in refactor_developer_prompt
    assert "Strictly follow" in refactor_developer_prompt
    assert "delete the `refactor_plan.md` file" in refactor_developer_prompt


@pytest.mark.anyio
async def test_pipeline_orchestrates_pr_creation_on_fallback(monkeypatch):
    """Verify that when no PR URL is found at the end of the pipeline, the orchestrator invokes gh pr create."""
    from unittest.mock import AsyncMock, MagicMock, patch
    import telegram_listener

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    mock_update = AsyncMock()
    mock_update.message = AsyncMock()
    mock_update.message.reply_text = AsyncMock()

    mock_context = MagicMock()

    mock_process = AsyncMock()
    mock_process.returncode = 0
    mock_process.communicate.return_value = (b"", b"")

    # We want to mock get_pr_url to return "" first, but when called after pr create, return a PR URL
    def mock_get_pr_url_side_effect():
        for call in mock_exec.call_args_list:
            if call[0] and call[0][0] == "gh" and call[0][1] == "pr" and call[0][2] == "create":
                return "https://github.com/owner/repo/pull/42"
        return ""

    with patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec, \
         patch.object(telegram_listener, "get_pr_url", side_effect=mock_get_pr_url_side_effect), \
         patch.object(telegram_listener, "get_git_changes", return_value=""), \
         patch.object(telegram_listener, "get_pytest_summary", return_value=""), \
         patch.object(telegram_listener, "run_command_and_stream", return_value=(0, "", "")):

        await telegram_listener.run_pipeline(
            mock_update, mock_context,
            "git@github.com:owner/repo.git", "test demand"
        )

        # Verify that gh pr create was executed
        mock_exec.assert_any_call(
            "gh", "pr", "create", "--fill", "--repo", "owner/repo",
            cwd="/workspace/project",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

    # Gather all reply_text calls
    calls = [str(call) for call in mock_update.message.reply_text.call_args_list]
    final_call = calls[-1] if calls else ""

    # Must report the opened PR link
    assert "https://github.com/owner/repo/pull/42" in final_call


SAMPLE_QUOTA_OUTPUT = """
GEMINI MODELS
  Models within this group: Gemini Flash, Gemini Pro

  Weekly Limit
[████████████████████████░░░░░░░░░░░░░░░░░░░░░░░░░░] 47.65%
    48% remaining · Refreshes in 92h 11m

  Five Hour Limit
[░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░] 0.00%
    Refreshes in 1h 49m

CLAUDE AND GPT MODELS
  Models within this group: Claude Opus, Claude Sonnet, GPT-OSS

  Weekly Limit
    [█████████████████████████░░░░░░░░░░░░░░░░░░░░░░░░░] 50.21%
    50% remaining · Refreshes in 137h 37m

  Five Hour Limit
    [███████████████████████████████████░░░░░░░░░░░░░░░] 70.23%
    70% remaining · Refreshes in 1h 3m
"""


def test_parse_model_quota_handles_zero_remaining_without_remaining_label():
    """When quota is exhausted, agy shows only the bar (0.00%) without a 'remaining' line."""
    output = """
GEMINI MODELS
  Five Hour Limit
[░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░] 0.00%
    Refreshes in 1h 49m
"""
    quota = parse_model_quota(output)
    assert quota["GEMINI MODELS"]["five_hour"]["remaining"] == 0.0
    assert quota["GEMINI MODELS"]["five_hour"]["usage"] == 100.0
    assert quota["GEMINI MODELS"]["five_hour"]["refresh"] == "1h 49m"

    rendered = format_model_quota_section(quota)
    assert "Gemini Five-Hour: <code>100%</code> used" in rendered


def test_parse_model_quota_extracts_usage_percentages():
    quota = parse_model_quota(SAMPLE_QUOTA_OUTPUT)
    assert quota["GEMINI MODELS"]["weekly"]["remaining"] == 48.0
    assert quota["GEMINI MODELS"]["weekly"]["usage"] == 52.0
    assert quota["GEMINI MODELS"]["weekly"]["refresh"] == "92h 11m"
    assert quota["GEMINI MODELS"]["five_hour"]["remaining"] == 0.0
    assert quota["GEMINI MODELS"]["five_hour"]["usage"] == 100.0
    assert quota["CLAUDE AND GPT MODELS"]["five_hour"]["usage"] == 30.0


def test_format_model_quota_section_renders_html():
    quota = parse_model_quota(SAMPLE_QUOTA_OUTPUT)
    rendered = format_model_quota_section(quota)
    assert "Model Quota Usage" in rendered
    assert "Gemini Five-Hour: <code>100%</code> used" in rendered
    assert "Gemini Weekly: <code>52%</code> used" in rendered
    assert "92h 11m" in rendered


@pytest.mark.anyio
async def test_send_status_no_session():
    import telegram_listener
    mock_update = AsyncMock()
    mock_update.message = AsyncMock()
    mock_update.message.reply_text = AsyncMock()
    
    with patch("telegram_listener.load_session", return_value=None):
        await telegram_listener.send_status(mock_update)
        
    mock_update.message.reply_text.assert_called_once_with(
        "ℹ️ No active session in memory."
    )


@pytest.mark.anyio
async def test_send_status_incomplete_session():
    import telegram_listener
    mock_update = AsyncMock()
    mock_update.message = AsyncMock()
    mock_update.message.reply_text = AsyncMock()
    
    with patch("telegram_listener.load_session", return_value={"repo_url": "https://github.com/owner/repo.git"}):
        await telegram_listener.send_status(mock_update)
        
    mock_update.message.reply_text.assert_called_once()
    args, kwargs = mock_update.message.reply_text.call_args
    status_msg = args[0]
    assert "ℹ️ No active session in memory." in status_msg
    assert "https://github.com/owner/repo.git" in status_msg
    assert kwargs.get("parse_mode") == "HTML"


@pytest.mark.anyio
async def test_send_status_complete_session():
    import telegram_listener
    mock_update = AsyncMock()
    mock_update.message = AsyncMock()
    mock_update.message.reply_text = AsyncMock()
    
    dummy_session = {
        "repo_url": "https://github.com/owner/repo.git",
        "demand": "do something & test",
        "git_branch": "feature/do-something",
        "last_completed_step": "Architect (Planning - PLAN)",
        "steps_status": {
            "Architect (Planning - PLAN)": "success"
        }
    }
    
    with patch("telegram_listener.load_session", return_value=dummy_session), \
         patch("telegram_listener.get_model_quota_summary", return_value="📉 <b>Model Quota Usage:</b>\n  • Gemini Five-Hour: <code>100%</code> used\n\n"):
        await telegram_listener.send_status(mock_update)
        
    mock_update.message.reply_text.assert_called_once()
    args, kwargs = mock_update.message.reply_text.call_args
    status_msg = args[0]
    assert "Aegis Session Memory" in status_msg
    assert "owner/repo.git" in status_msg
    assert "do something &amp; test" in status_msg
    assert "feature/do-something" in status_msg
    assert "Architect (Planning - PLAN)" in status_msg
    assert "Model Quota Usage" in status_msg
    assert "100%" in status_msg


@pytest.mark.anyio
async def test_run_pipeline_cancellation(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock, patch
    import telegram_listener
    import asyncio

    mock_update = AsyncMock()
    mock_update.message = AsyncMock()
    mock_update.message.reply_text = AsyncMock()
    
    mock_context = MagicMock()
    
    dummy_session = {
        "repo_url": "https://github.com/owner/repo.git",
        "demand": "test cancellation",
        "git_branch": "feature/cancellation",
        "last_completed_step": "Architect (Planning - PLAN)",
        "steps_status": {
            "Architect (Planning - PLAN)": "success"
        }
    }
    
    mock_save = MagicMock()
    monkeypatch.setattr(telegram_listener, "load_session", lambda *args, **kwargs: dummy_session)
    monkeypatch.setattr(telegram_listener, "save_session", mock_save)
    
    async def mock_run_command_and_stream(*args, **kwargs):
        try:
            await asyncio.sleep(10)
            return 0, "", ""
        except asyncio.CancelledError:
            raise

    monkeypatch.setattr(telegram_listener, "run_command_and_stream", mock_run_command_and_stream)
    
    mock_process = AsyncMock()
    mock_process.returncode = 0
    mock_process.communicate.return_value = (b"", b"")
    
    with patch("asyncio.create_subprocess_exec", return_value=mock_process), \
         patch("os.path.exists", return_value=True):
        
        task = asyncio.create_task(
            telegram_listener.run_pipeline(
                mock_update, mock_context,
                "https://github.com/owner/repo.git", "test cancellation",
                is_resume=True
            )
        )
        
        await asyncio.sleep(0.1)
        task.cancel()
        
        with pytest.raises(asyncio.CancelledError):
            await task
            
    mock_save.assert_called()
    args, kwargs = mock_save.call_args
    assert args[0] == "https://github.com/owner/repo.git"
    assert args[1] == "test cancellation"
    assert args[2] == "Architect (Planning - PLAN)"
    assert args[3]["Test Developer (Testing - RED)"] == "failed"
    
    calls = [str(call) for call in mock_update.message.reply_text.call_args_list]
    assert any("Pipeline stopped in step" in call for call in calls)


@pytest.mark.anyio
async def test_handle_stop_no_active_task():
    from unittest.mock import AsyncMock, MagicMock, patch
    import telegram_listener
    mock_update = AsyncMock()
    mock_update.effective_chat.id = 12345
    mock_update.message = AsyncMock()
    mock_update.message.reply_text = AsyncMock()
    mock_context = MagicMock()
    
    telegram_listener.ACTIVE_TASKS.clear()
    
    with patch("telegram_listener.ALLOWED_CHAT_ID", "12345"):
        await telegram_listener.handle_stop(mock_update, mock_context)
    mock_update.message.reply_text.assert_called_once_with(
        "ℹ️ No running pipeline to stop."
    )


@pytest.mark.anyio
async def test_handle_stop_with_active_task():
    from unittest.mock import AsyncMock, MagicMock, patch
    import telegram_listener
    mock_update = AsyncMock()
    mock_update.effective_chat.id = 12345
    mock_update.message = AsyncMock()
    mock_update.message.reply_text = AsyncMock()
    mock_context = MagicMock()
    
    mock_task = MagicMock()
    mock_task.done.return_value = False
    
    chat_id = "12345"
    telegram_listener.ACTIVE_TASKS[chat_id] = mock_task
    
    with patch("telegram_listener.ALLOWED_CHAT_ID", "12345"):
        await telegram_listener.handle_stop(mock_update, mock_context)
    
    mock_task.cancel.assert_called_once()
    mock_update.message.reply_text.assert_called_once_with(
        "🛑 Request to stop the pipeline sent."
    )
    
    telegram_listener.ACTIVE_TASKS.clear()




@pytest.mark.anyio
async def test_handle_review_invalid_reference():
    from unittest.mock import AsyncMock, MagicMock, patch
    import telegram_listener

    mock_update = AsyncMock()
    mock_update.effective_chat.id = 12345
    mock_update.message = AsyncMock()
    mock_update.message.text = "/review invalid"
    mock_update.message.reply_text = AsyncMock()
    mock_context = MagicMock()

    with patch("telegram_listener.ALLOWED_CHAT_ID", "12345"):
        await telegram_listener.handle_review(mock_update, mock_context)

    mock_update.message.reply_text.assert_called_once()
    args, kwargs = mock_update.message.reply_text.call_args
    assert "Usage" in args[0]


@pytest.mark.anyio
async def test_handle_review_runs_pr_review():
    from unittest.mock import AsyncMock, MagicMock, patch
    import telegram_listener

    mock_update = AsyncMock()
    mock_update.effective_chat.id = 12345
    mock_update.message = AsyncMock()
    mock_update.message.text = "/review owner/repo#42"
    mock_update.message.reply_text = AsyncMock()
    mock_context = MagicMock()

    with patch("telegram_listener.ALLOWED_CHAT_ID", "12345"), \
         patch("telegram_listener.run_pr_review", new_callable=AsyncMock) as mock_run:
        await telegram_listener.handle_review(mock_update, mock_context)

    mock_run.assert_called_once_with(
        mock_update, mock_context, "https://github.com/owner/repo.git", 42
    )


@pytest.mark.anyio
async def test_run_pr_review_returns_review_only(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock, patch
    import telegram_listener

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    mock_update = AsyncMock()
    mock_update.message = AsyncMock()
    mock_update.message.reply_text = AsyncMock()

    mock_context = MagicMock()

    mock_process = AsyncMock()
    mock_process.returncode = 0
    mock_process.communicate.return_value = (b"", b"")

    review_output = "## Summary\nLooks good.\n\n## Issues\nNone."

    with patch("asyncio.create_subprocess_exec", return_value=mock_process), \
         patch("os.path.exists", return_value=False), \
         patch.object(telegram_listener, "fetch_pr_context", new_callable=AsyncMock, return_value="PR context"), \
         patch.object(telegram_listener, "run_command_and_stream", return_value=(0, review_output, "")):
        await telegram_listener.run_pr_review(
            mock_update, mock_context, "git@github.com:owner/repo.git", 42
        )

    calls = mock_update.message.reply_text.call_args_list
    assert len(calls) == 1
    review_msg = calls[0][0][0]
    assert "Looks good" in review_msg
    assert "completed successfully" not in review_msg
    assert "PR Created" not in review_msg
    assert "Files changed" not in review_msg


@pytest.mark.anyio
async def test_run_pr_review_clone_failure(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock, patch
    import telegram_listener

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    mock_update = AsyncMock()
    mock_update.message = AsyncMock()
    mock_update.message.reply_text = AsyncMock()
    mock_context = MagicMock()

    mock_process = AsyncMock()
    mock_process.returncode = 1
    mock_process.communicate.return_value = (b"", b"clone failed")

    with patch("asyncio.create_subprocess_exec", return_value=mock_process), \
         patch("os.path.exists", return_value=False):
        await telegram_listener.run_pr_review(
            mock_update, mock_context, "git@github.com:owner/repo.git", 42
        )

    mock_update.message.reply_text.assert_called_once()
    assert "Failed to clone" in mock_update.message.reply_text.call_args[0][0]


@pytest.mark.anyio
async def test_run_pr_review_checkout_failure(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock, patch
    import telegram_listener

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    mock_update = AsyncMock()
    mock_update.message = AsyncMock()
    mock_update.message.reply_text = AsyncMock()
    mock_context = MagicMock()

    clone_process = AsyncMock()
    clone_process.returncode = 0
    clone_process.communicate.return_value = (b"", b"")

    checkout_process = AsyncMock()
    checkout_process.returncode = 1
    checkout_process.communicate.return_value = (b"", b"checkout failed")

    with patch("asyncio.create_subprocess_exec", side_effect=[clone_process, checkout_process]), \
         patch("os.path.exists", return_value=False):
        await telegram_listener.run_pr_review(
            mock_update, mock_context, "git@github.com:owner/repo.git", 42
        )

    mock_update.message.reply_text.assert_called_once()
    assert "Failed to checkout PR" in mock_update.message.reply_text.call_args[0][0]


@pytest.mark.anyio
async def test_send_review_text_splits_long_messages():
    import telegram_listener

    mock_update = AsyncMock()
    mock_update.message = AsyncMock()
    mock_update.message.reply_text = AsyncMock()

    long_review = "x" * 9000
    await telegram_listener._send_review_text(mock_update, long_review)

    assert mock_update.message.reply_text.call_count == 3
    # All chunks must be sent as HTML (so formatting/highlighting is applied).
    for call in mock_update.message.reply_text.call_args_list:
        assert call.kwargs.get("parse_mode") == "HTML"


def test_render_markdown_code_block_gets_language_marker():
    import telegram_listener

    md = "Here:\n\n```python\ndef foo():\n    return 1 < 2\n```\n"
    messages = telegram_listener.render_markdown_messages(md)
    joined = "\n".join(messages)
    assert '<pre><code class="language-python">' in joined
    assert "</code></pre>" in joined
    # Code content must be HTML-escaped inside the block.
    assert "1 &lt; 2" in joined


def test_render_markdown_inline_formatting():
    import telegram_listener

    md = "# Title\n\nThis is **bold**, *italic*, and `code` with a [link](https://x.io/a?b=1&c=2)."
    out = "\n".join(telegram_listener.render_markdown_messages(md))
    assert "<b>Title</b>" in out
    assert "<b>bold</b>" in out
    assert "<i>italic</i>" in out
    assert "<code>code</code>" in out
    # URL should be escaped exactly once (no double escaping).
    assert '<a href="https://x.io/a?b=1&amp;c=2">link</a>' in out


def test_render_markdown_code_block_without_language():
    import telegram_listener

    md = "```\nplain code\n```"
    out = "\n".join(telegram_listener.render_markdown_messages(md))
    assert "<pre>plain code</pre>" in out


def test_render_markdown_never_splits_inside_message_limit():
    import telegram_listener

    md = "```python\n" + "\n".join(f"line_{i} = {i}" for i in range(2000)) + "\n```"
    messages = telegram_listener.render_markdown_messages(md, max_len=1000)
    for m in messages:
        assert len(m) <= 1000
        # Every chunk must have balanced <pre> open/close tags (never split mid-block).
        assert m.count("<pre") == m.count("</pre>")


@pytest.mark.anyio
async def test_run_pr_review_errors_when_no_credentials(monkeypatch):
    """With no token, no gh CLI, and no SSH key, review must fail with a helpful message."""
    from unittest.mock import AsyncMock, MagicMock, patch
    import telegram_listener

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    mock_update = AsyncMock()
    mock_update.message = AsyncMock()
    mock_update.message.reply_text = AsyncMock()
    mock_context = MagicMock()

    with patch.object(telegram_listener, "_gh_auth_token", AsyncMock(return_value=None)), \
         patch.object(telegram_listener, "_ssh_github_available", AsyncMock(return_value=False)):
        await telegram_listener.run_pr_review(
            mock_update, mock_context, "https://github.com/owner/repo.git", 42
        )

    mock_update.message.reply_text.assert_called_once()
    msg = mock_update.message.reply_text.call_args[0][0]
    assert "GITHUB_TOKEN" in msg
    assert "gh auth login" in msg


@pytest.mark.anyio
async def test_resolve_clone_url_prefers_env_token(monkeypatch):
    import telegram_listener

    url, method, error = await telegram_listener.resolve_clone_url(
        "https://github.com/owner/repo.git", "gho_envtoken"
    )
    assert error is None
    assert method == "github-token"
    assert url == "https://x-access-token:gho_envtoken@github.com/owner/repo.git"


@pytest.mark.anyio
async def test_resolve_clone_url_falls_back_to_gh_cli(monkeypatch):
    from unittest.mock import AsyncMock, patch
    import telegram_listener

    with patch.object(telegram_listener, "_gh_auth_token", AsyncMock(return_value="gho_ghtoken")):
        url, method, error = await telegram_listener.resolve_clone_url(
            "https://github.com/owner/repo.git", None
        )
    assert error is None
    assert method == "gh-cli"
    assert url == "https://x-access-token:gho_ghtoken@github.com/owner/repo.git"


@pytest.mark.anyio
async def test_resolve_clone_url_falls_back_to_ssh(monkeypatch):
    from unittest.mock import AsyncMock, patch
    import telegram_listener

    with patch.object(telegram_listener, "_gh_auth_token", AsyncMock(return_value=None)), \
         patch.object(telegram_listener, "_ssh_github_available", AsyncMock(return_value=True)):
        url, method, error = await telegram_listener.resolve_clone_url(
            "https://github.com/owner/repo.git", None
        )
    assert error is None
    assert method == "ssh"
    assert url == "git@github.com:owner/repo.git"


@pytest.mark.anyio
async def test_resolve_clone_url_ssh_url_unchanged(monkeypatch):
    import telegram_listener

    url, method, error = await telegram_listener.resolve_clone_url(
        "git@github.com:owner/repo.git", None
    )
    assert error is None
    assert method == "ssh"
    assert url == "git@github.com:owner/repo.git"


@pytest.mark.anyio
async def test_run_pr_review_removes_existing_project_dir(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock, patch
    import telegram_listener

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    mock_update = AsyncMock()
    mock_update.message = AsyncMock()
    mock_update.message.reply_text = AsyncMock()
    mock_context = MagicMock()

    rm_process = AsyncMock()
    rm_process.returncode = 0
    clone_process = AsyncMock()
    clone_process.returncode = 0
    clone_process.communicate.return_value = (b"", b"")
    checkout_process = AsyncMock()
    checkout_process.returncode = 0
    checkout_process.communicate.return_value = (b"", b"")

    with patch("asyncio.create_subprocess_exec", side_effect=[rm_process, clone_process, checkout_process]), \
         patch("os.path.exists", return_value=True), \
         patch.object(telegram_listener, "fetch_pr_context", new_callable=AsyncMock, return_value="PR context"), \
         patch.object(telegram_listener, "run_command_and_stream", return_value=(0, "Review text", "")):
        await telegram_listener.run_pr_review(
            mock_update, mock_context, "git@github.com:owner/repo.git", 42
        )

    mock_update.message.reply_text.assert_called_once()
    assert "Review text" in mock_update.message.reply_text.call_args[0][0]


@pytest.mark.anyio
async def test_run_pr_review_agent_failure(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock, patch
    import telegram_listener

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    mock_update = AsyncMock()
    mock_update.message = AsyncMock()
    mock_update.message.reply_text = AsyncMock()
    mock_context = MagicMock()

    clone_process = AsyncMock()
    clone_process.returncode = 0
    clone_process.communicate.return_value = (b"", b"")
    checkout_process = AsyncMock()
    checkout_process.returncode = 0
    checkout_process.communicate.return_value = (b"", b"")

    with patch("asyncio.create_subprocess_exec", side_effect=[clone_process, checkout_process]), \
         patch("os.path.exists", return_value=False), \
         patch.object(telegram_listener, "fetch_pr_context", new_callable=AsyncMock, return_value="PR context"), \
         patch.object(telegram_listener, "run_command_and_stream", return_value=(1, "partial", "agent failed")):
        await telegram_listener.run_pr_review(
            mock_update, mock_context, "git@github.com:owner/repo.git", 42
        )

    mock_update.message.reply_text.assert_called_once()
    assert "PR review failed" in mock_update.message.reply_text.call_args[0][0]


@pytest.mark.anyio
async def test_run_pr_review_empty_output(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock, patch
    import telegram_listener

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    mock_update = AsyncMock()
    mock_update.message = AsyncMock()
    mock_update.message.reply_text = AsyncMock()
    mock_context = MagicMock()

    clone_process = AsyncMock()
    clone_process.returncode = 0
    clone_process.communicate.return_value = (b"", b"")
    checkout_process = AsyncMock()
    checkout_process.returncode = 0
    checkout_process.communicate.return_value = (b"", b"")

    with patch("asyncio.create_subprocess_exec", side_effect=[clone_process, checkout_process]), \
         patch("os.path.exists", return_value=False), \
         patch.object(telegram_listener, "fetch_pr_context", new_callable=AsyncMock, return_value="PR context"), \
         patch.object(telegram_listener, "run_command_and_stream", return_value=(0, "   ", "")):
        await telegram_listener.run_pr_review(
            mock_update, mock_context, "git@github.com:owner/repo.git", 42
        )

    mock_update.message.reply_text.assert_called_once()
    assert "returned no output" in mock_update.message.reply_text.call_args[0][0]


@pytest.mark.anyio
async def test_run_pr_review_handles_exception(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock, patch
    import telegram_listener

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    mock_update = AsyncMock()
    mock_update.message = AsyncMock()
    mock_update.message.reply_text = AsyncMock()
    mock_context = MagicMock()

    with patch("os.path.exists", side_effect=RuntimeError("boom")):
        await telegram_listener.run_pr_review(
            mock_update, mock_context, "git@github.com:owner/repo.git", 42
        )

    mock_update.message.reply_text.assert_called_once()
    assert "PR review error" in mock_update.message.reply_text.call_args[0][0]


@pytest.mark.anyio
async def test_fetch_pr_context_combines_metadata_and_diff():
    import telegram_listener

    view_process = AsyncMock()
    view_process.returncode = 0
    view_process.communicate.return_value = (b"title: Fix bug", b"")

    diff_process = AsyncMock()
    diff_process.returncode = 0
    diff_process.communicate.return_value = (b"+added line", b"")

    with patch("asyncio.create_subprocess_exec", side_effect=[view_process, diff_process]):
        context = await telegram_listener.fetch_pr_context("owner/repo", 7, "/workspace/project")

    assert "title: Fix bug" in context
    assert "--- Diff ---" in context
    assert "+added line" in context


@pytest.mark.anyio
async def test_fetch_pr_context_truncates_large_diff():
    import telegram_listener

    view_process = AsyncMock()
    view_process.returncode = 0
    view_process.communicate.return_value = (b"title: Big PR", b"")

    diff_process = AsyncMock()
    diff_process.returncode = 0
    diff_process.communicate.return_value = (b"x" * 200_000, b"")

    with patch("asyncio.create_subprocess_exec", side_effect=[view_process, diff_process]):
        context = await telegram_listener.fetch_pr_context(
            "owner/repo", 7, "/workspace/project", max_diff_chars=1000
        )

    assert "title: Big PR" in context
    assert "diff truncated" in context
    assert len(context) < 200_000


@pytest.mark.anyio
async def test_run_pr_review_uses_cursor_ask_mode(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock, patch
    import telegram_listener

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("AGENT_TOOL", "cursor")

    mock_update = AsyncMock()
    mock_update.message = AsyncMock()
    mock_update.message.reply_text = AsyncMock()
    mock_context = MagicMock()

    clone_process = AsyncMock()
    clone_process.returncode = 0
    clone_process.communicate.return_value = (b"", b"")
    checkout_process = AsyncMock()
    checkout_process.returncode = 0
    checkout_process.communicate.return_value = (b"", b"")

    captured_command = []

    async def capture_stream(command, cwd="/workspace"):
        captured_command.extend(command)
        return 0, "Review complete", ""

    with patch("asyncio.create_subprocess_exec", side_effect=[clone_process, checkout_process]), \
         patch("os.path.exists", return_value=False), \
         patch.object(telegram_listener, "fetch_pr_context", new_callable=AsyncMock, return_value="PR context"), \
         patch.object(telegram_listener, "run_command_and_stream", side_effect=capture_stream):
        await telegram_listener.run_pr_review(
            mock_update, mock_context, "git@github.com:owner/repo.git", 42
        )

    assert "--mode" in captured_command
    assert captured_command[captured_command.index("--mode") + 1] == "ask"
    assert "--force" not in captured_command


def test_terminate_process_tree_sends_sigterm():
    from unittest.mock import MagicMock, patch
    import signal
    import telegram_listener

    mock_process = MagicMock()
    mock_process.pid = 4242

    with patch("telegram_listener.os.getpgid", return_value=4242) as mock_getpgid, \
         patch("telegram_listener.os.killpg") as mock_killpg:
        telegram_listener._terminate_process_tree(mock_process)

    mock_getpgid.assert_called_once_with(4242)
    mock_killpg.assert_called_once_with(4242, signal.SIGTERM)


def test_terminate_process_tree_sends_sigkill_when_forced():
    from unittest.mock import MagicMock, patch
    import signal
    import telegram_listener

    mock_process = MagicMock()
    mock_process.pid = 4242

    with patch("telegram_listener.os.getpgid", return_value=4242), \
         patch("telegram_listener.os.killpg") as mock_killpg:
        telegram_listener._terminate_process_tree(mock_process, force=True)

    mock_killpg.assert_called_once_with(4242, signal.SIGKILL)


@pytest.mark.anyio
async def test_run_pr_review_registers_and_clears_active_task(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock, patch
    import telegram_listener

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    telegram_listener.ACTIVE_TASKS.clear()

    mock_update = AsyncMock()
    mock_update.effective_chat.id = 12345
    mock_update.message = AsyncMock()
    mock_update.message.reply_text = AsyncMock()
    mock_context = MagicMock()

    mock_process = AsyncMock()
    mock_process.returncode = 0
    mock_process.communicate.return_value = (b"", b"")

    review_output = "Review complete."

    with patch("telegram_listener.ALLOWED_CHAT_ID", "12345"), \
         patch("asyncio.create_subprocess_exec", return_value=mock_process), \
         patch("os.path.exists", return_value=False), \
         patch.object(telegram_listener, "fetch_pr_context", new_callable=AsyncMock, return_value="PR context"), \
         patch.object(telegram_listener, "run_command_and_stream", return_value=(0, review_output, "")):
        await telegram_listener.run_pr_review(
            mock_update, mock_context, "git@github.com:owner/repo.git", 42
        )

    assert "12345" not in telegram_listener.ACTIVE_TASKS


@pytest.mark.anyio
async def test_run_pr_review_cancelled_during_clone(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock, patch
    import telegram_listener

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    telegram_listener.ACTIVE_TASKS.clear()

    mock_update = AsyncMock()
    mock_update.effective_chat.id = 12345
    mock_update.message = AsyncMock()
    mock_update.message.reply_text = AsyncMock()
    mock_context = MagicMock()

    clone_process = AsyncMock()

    async def slow_communicate():
        await asyncio.sleep(3600)
        return b"", b""

    clone_process.communicate = slow_communicate

    with patch("telegram_listener.ALLOWED_CHAT_ID", "12345"), \
         patch("asyncio.create_subprocess_exec", return_value=clone_process), \
         patch("os.path.exists", return_value=False), \
         patch.object(telegram_listener, "_terminate_process_tree") as mock_terminate:
        task = asyncio.create_task(
            telegram_listener.run_pr_review(
                mock_update, mock_context, "git@github.com:owner/repo.git", 42
            )
        )
        await asyncio.sleep(0.05)
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

    mock_terminate.assert_called()
    calls = [str(call) for call in mock_update.message.reply_text.call_args_list]
    assert any("PR review stopped" in call for call in calls)
    assert "12345" not in telegram_listener.ACTIVE_TASKS


@pytest.mark.anyio
async def test_handle_continue_rejects_when_pipeline_active():
    from unittest.mock import AsyncMock, MagicMock, patch
    import telegram_listener

    mock_update = AsyncMock()
    mock_update.effective_chat.id = 12345
    mock_update.message = AsyncMock()
    mock_update.message.reply_text = AsyncMock()
    mock_context = MagicMock()

    mock_task = MagicMock()
    mock_task.done.return_value = False
    telegram_listener.ACTIVE_TASKS["12345"] = mock_task

    with patch("telegram_listener.ALLOWED_CHAT_ID", "12345"), \
         patch("telegram_listener.run_pipeline", new_callable=AsyncMock) as mock_run:
        await telegram_listener.handle_continue(mock_update, mock_context)

    mock_run.assert_not_called()
    mock_update.message.reply_text.assert_called_once()
    assert "/stop" in mock_update.message.reply_text.call_args[0][0]

    telegram_listener.ACTIVE_TASKS.clear()


@pytest.mark.anyio
async def test_handle_review_rejects_when_pipeline_active():
    from unittest.mock import AsyncMock, MagicMock, patch
    import telegram_listener

    mock_update = AsyncMock()
    mock_update.effective_chat.id = 12345
    mock_update.message = AsyncMock()
    mock_update.message.text = "/review owner/repo#42"
    mock_update.message.reply_text = AsyncMock()
    mock_context = MagicMock()

    mock_task = MagicMock()
    mock_task.done.return_value = False
    telegram_listener.ACTIVE_TASKS["12345"] = mock_task

    with patch("telegram_listener.ALLOWED_CHAT_ID", "12345"), \
         patch("telegram_listener.run_pr_review", new_callable=AsyncMock) as mock_run:
        await telegram_listener.handle_review(mock_update, mock_context)

    mock_run.assert_not_called()
    mock_update.message.reply_text.assert_called_once()
    assert "/stop" in mock_update.message.reply_text.call_args[0][0]

    telegram_listener.ACTIVE_TASKS.clear()


@pytest.mark.anyio
async def test_handle_demand_rejects_new_pipeline_when_active():
    from unittest.mock import AsyncMock, MagicMock, patch
    import telegram_listener

    mock_update = AsyncMock()
    mock_update.effective_chat.id = 12345
    mock_update.message = AsyncMock()
    mock_update.message.text = "owner/repo: add feature"
    mock_update.message.reply_text = AsyncMock()
    mock_context = MagicMock()

    mock_task = MagicMock()
    mock_task.done.return_value = False
    telegram_listener.ACTIVE_TASKS["12345"] = mock_task

    with patch("telegram_listener.ALLOWED_CHAT_ID", "12345"), \
         patch("telegram_listener.classify_intent", new_callable=AsyncMock, return_value="NEW_DEMAND"), \
         patch("telegram_listener.run_pipeline", new_callable=AsyncMock) as mock_run:
        await telegram_listener.handle_demand(mock_update, mock_context)

    mock_run.assert_not_called()
    mock_update.message.reply_text.assert_called_once()
    assert "/stop" in mock_update.message.reply_text.call_args[0][0]

    telegram_listener.ACTIVE_TASKS.clear()

