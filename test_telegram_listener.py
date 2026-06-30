import os
import pytest
from telegram_listener import AntigravityAgentCLI, sanitize_environment

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
