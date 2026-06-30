import os
import pytest
from telegram_listener import AntigravityAgentCLI, sanitize_environment, parse_demand

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

