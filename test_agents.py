import pytest
from unittest.mock import AsyncMock, patch

from agents import AgentRegistry
from agents.adapters.aider import AiderAgentCLI
from agents.adapters.claude import ClaudeCodeAgentCLI
from agents.adapters.cursor import CursorAgentCLI
from agents.auth.cursor import CursorAuthResolver
from agents.pipeline import PIPELINE_CONFIG, resolve_pipeline_config
from agents.review_pipeline import PR_REVIEW_CONFIG, resolve_review_pipeline_config
from agents.registry import AgentRegistry as RegistryClass
from agents.tool_specs import get_registered_tools, validate_tool
from telegram_listener import classify_intent, get_model_quota_summary


# --- Registry ---


def test_registry_resolves_all_tool_specs():
    for tool in get_registered_tools():
        agent = AgentRegistry.get_agent(tool)
        assert agent is not None
        assert hasattr(agent, "build_command")


def test_registry_unknown_tool_raises():
    with pytest.raises(ValueError, match="not registered"):
        AgentRegistry.get_agent("nonexistent-tool")


def test_registry_register_and_resolve():
    class DummyCLI:
        def build_command(self, prompt, model, reasoning_budget, timeout=None):
            return ["dummy", prompt]

    RegistryClass.register("_test_dummy", DummyCLI)
    try:
        agent = RegistryClass.get_agent("_test_dummy")
        assert agent.build_command("hi", "m", "low") == ["dummy", "hi"]
    finally:
        RegistryClass._registry.pop("_test_dummy", None)


# --- Adapters ---


def test_claude_cli_build_command():
    cmd = ClaudeCodeAgentCLI().build_command("Fix tests", "claude-sonnet", "high")
    assert cmd == ["claude", "-p", "Fix tests", "-y"]


def test_aider_cli_build_command():
    cmd = AiderAgentCLI().build_command("Add feature", "gpt-4", "medium")
    assert cmd == [
        "aider",
        "--model", "gpt-4",
        "--message", "Add feature",
        "--yes",
        "--no-auto-commits",
    ]


def test_agy_cli_maps_model_slugs():
    from agents.adapters.agy import AntigravityAgentCLI

    cli = AntigravityAgentCLI()
    cmd = cli.build_command("Plan", "gemini-3.1-pro", "high")
    assert "Gemini 3.1 Pro (High)" in cmd
    assert cmd[0] == "agy"


def test_agy_cli_passes_through_unknown_model_slug():
    from agents.adapters.agy import AntigravityAgentCLI

    cmd = AntigravityAgentCLI().build_command("Plan", "custom-model", "low")
    assert "custom-model (Low)" in cmd


# --- Cursor auth ---


def test_cursor_auth_resolver_skips_empty_api_key():
    base = ["agent", "-p", "x"]
    assert CursorAuthResolver.augment_command(base) == base


def test_cursor_auth_resolver_skips_whitespace_api_key(monkeypatch):
    monkeypatch.setenv("CURSOR_API_KEY", "   ")
    base = ["agent", "-p", "x"]
    assert CursorAuthResolver.augment_command(base) == base


def test_cursor_auth_resolver_appends_api_key(monkeypatch):
    monkeypatch.setenv("CURSOR_API_KEY", "cursor_secret")
    base = ["agent", "-p", "x"]
    assert CursorAuthResolver.augment_command(base) == base + ["--api-key", "cursor_secret"]


def test_cursor_auth_resolver_does_not_mutate_input(monkeypatch):
    monkeypatch.setenv("CURSOR_API_KEY", "key")
    base = ["agent", "-p", "x"]
    copy_base = list(base)
    CursorAuthResolver.augment_command(base)
    assert base == copy_base


# --- Pipeline ---


def test_resolve_pipeline_config_explicit_tool():
    resolved = resolve_pipeline_config("claude")
    assert all(step["tool"] == "claude" for step in resolved)


def test_resolve_pipeline_config_from_env(monkeypatch):
    monkeypatch.setenv("AGENT_TOOL", "aider")
    resolved = resolve_pipeline_config()
    assert all(step["tool"] == "aider" for step in resolved)


def test_resolve_pipeline_config_rejects_unknown_tool():
    with pytest.raises(ValueError, match="Unknown AGENT_TOOL"):
        resolve_pipeline_config("invalid")


def test_resolve_pipeline_config_deep_copies_steps():
    resolved = resolve_pipeline_config("agy")
    resolved[0]["tool"] = "mutated"
    assert PIPELINE_CONFIG[0]["tool"] == "agy"


def test_resolve_pipeline_config_preserves_step_metadata():
    resolved = resolve_pipeline_config("cursor")
    step = resolved[0]
    assert step["step_name"] == "Architect (Planning - PLAN)"
    assert step["model"] == "gemini-3.1-pro"
    assert "{demand}" in step["prompt"]


def test_resolve_review_pipeline_config_explicit_tool():
    resolved = resolve_review_pipeline_config("claude")
    assert len(resolved) == 1
    assert resolved[0]["tool"] == "claude"
    assert resolved[0]["step_name"] == "PR Reviewer"
    assert "{pr_number}" in resolved[0]["prompt"]


def test_resolve_review_pipeline_config_deep_copies_steps():
    resolved = resolve_review_pipeline_config("agy")
    resolved[0]["tool"] = "mutated"
    assert PR_REVIEW_CONFIG[0]["tool"] == "agy"


# --- validate_tool ---


@pytest.mark.parametrize("raw,expected", [
    ("agy", "agy"),
    ("CURSOR", "cursor"),
    ("  claude  ", "claude"),
    ("", "agy"),
    (None, "agy"),
])
def test_validate_tool_normalization(raw, expected):
    assert validate_tool(raw) == expected


# --- Orchestrator integration ---


@pytest.mark.anyio
async def test_classify_intent_uses_agy_when_configured():
    mock_process = AsyncMock()
    mock_process.returncode = 0
    mock_process.communicate.return_value = (b"RESUME\n", b"")

    with patch("telegram_listener.DEFAULT_AGENT_TOOL", "agy"), \
         patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec:
        result = await classify_intent("continue please")
        assert result == "RESUME"
        cmd = mock_exec.call_args[0]
        assert cmd[0] == "agy"
        assert "Gemini 3.5 Flash (Low)" in cmd


@pytest.mark.anyio
async def test_classify_intent_uses_cursor_when_configured():
    mock_process = AsyncMock()
    mock_process.returncode = 0
    mock_process.communicate.return_value = (b"QUERY_STATUS\n", b"")

    with patch("telegram_listener.DEFAULT_AGENT_TOOL", "cursor"), \
         patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec:
        result = await classify_intent("what is the status?")
        assert result == "QUERY_STATUS"
        cmd = mock_exec.call_args[0]
        assert cmd[0] == "agent"
        assert "--model" in cmd
        assert cmd[cmd.index("--model") + 1] == "auto"


def test_get_model_quota_summary_empty_when_tool_has_no_quota():
    with patch("telegram_listener.DEFAULT_AGENT_TOOL", "cursor"):
        assert get_model_quota_summary() == ""
