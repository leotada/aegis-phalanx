import os
import pytest
from telegram_listener import (
    AntigravityAgentCLI,
    sanitize_environment,
    parse_demand,
    save_session,
    load_session,
    clear_session,
    classify_intent
)

def test_antigravity_cli_timeout_argument():
    cli = AntigravityAgentCLI()
    cmd = cli.build_command("Test prompt", "gemini-3.5-flash", "low")
    
    # We want `--print-timeout 15m` to be present in the build command
    assert "--print-timeout" in cmd
    assert "15m" in cmd

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

from unittest.mock import AsyncMock, patch

@pytest.mark.anyio
async def test_classify_intent_via_agy_success():
    mock_process = AsyncMock()
    mock_process.returncode = 0
    mock_process.communicate.return_value = (b"RESUME\n", b"")
    
    with patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec:
        res = await classify_intent("some message")
        assert res == "RESUME"
        mock_exec.assert_called_once()
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



