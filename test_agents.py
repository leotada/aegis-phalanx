import pytest
from unittest.mock import AsyncMock, patch

from agents import AgentRegistry
from agents.adapters.aider import AiderAgentCLI
from agents.adapters.claude import ClaudeCodeAgentCLI
from agents.adapters.cursor import CursorAgentCLI
from agents.auth.cursor import CursorAuthResolver
from agents.pipeline import (
    PIPELINE_CONFIG,
    DEFAULT_PIPELINE_MODE,
    MODE_EASY,
    MODE_HARD,
    normalize_mode,
    resolve_pipeline_config,
)
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
    cmd = ClaudeCodeAgentCLI().build_command("Fix tests", "gemini-3.5-flash", "high")
    assert cmd == [
        "claude",
        "--print",
        "--model", "sonnet",
        "--effort", "high",
        "--dangerously-skip-permissions",
        "Fix tests",
    ]


def test_claude_cli_maps_pro_model_and_passes_claude_alias():
    cli = ClaudeCodeAgentCLI()
    pro_cmd = cli.build_command("Plan", "gemini-3.1-pro", "medium")
    assert pro_cmd[pro_cmd.index("--model") + 1] == "opus"

    pro37_cmd = cli.build_command("Plan", "gemini-3.7-pro", "medium")
    assert pro37_cmd[pro37_cmd.index("--model") + 1] == "opus"

    flash37_cmd = cli.build_command("Plan", "gemini-3.7-flash", "low")
    assert flash37_cmd[flash37_cmd.index("--model") + 1] == "sonnet"

    alias_cmd = cli.build_command("Plan", "sonnet", "low")
    assert alias_cmd[alias_cmd.index("--model") + 1] == "sonnet"


def test_claude_cli_read_only_uses_plan_permission_mode():
    cmd = ClaudeCodeAgentCLI().build_command(
        "Review prompt", "gemini-3.5-flash", "high", read_only=True
    )
    assert "--permission-mode" in cmd
    assert cmd[cmd.index("--permission-mode") + 1] == "plan"
    assert "--dangerously-skip-permissions" not in cmd
    assert cmd[-1] == "Review prompt"


def test_claude_cli_falls_back_on_unknown_effort():
    cmd = ClaudeCodeAgentCLI().build_command("Fix", "opus", "ultra")
    assert cmd[cmd.index("--effort") + 1] == "medium"


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
    cmd_pro = cli.build_command("Plan", "gemini-3.7-pro", "high")
    assert "Gemini 3.7 Pro (High)" in cmd_pro
    assert cmd_pro[0] == "agy"

    cmd_flash = cli.build_command("Code", "gemini-3.7-flash", "medium")
    assert "Gemini 3.7 Flash (Medium)" in cmd_flash
    assert cmd_flash[0] == "agy"

    cmd_flash36 = cli.build_command("Code", "gemini-3.6-flash", "low")
    assert "Gemini 3.6 Flash (Low)" in cmd_flash36


def test_agy_cli_read_only_preserves_dangerously_skip_permissions():
    from agents.adapters.agy import AntigravityAgentCLI

    cmd = AntigravityAgentCLI().build_command("Review", "gemini-3.7-flash", "high", read_only=True)
    assert "--dangerously-skip-permissions" in cmd
    assert "--mode" not in cmd


def test_agy_cli_passes_through_unknown_model_slug():
    from agents.adapters.agy import AntigravityAgentCLI

    cmd = AntigravityAgentCLI().build_command("Plan", "custom-model", "low")
    assert "custom-model (Low)" in cmd


def test_agy_cli_defaults_to_gemini_37_flash():
    from agents.adapters.agy import AntigravityAgentCLI

    cmd = AntigravityAgentCLI().build_command("Plan", None, None)
    assert "Gemini 3.7 Flash (Medium)" in cmd


# --- Cursor auth ---


def test_cursor_auth_resolver_skips_empty_api_key():
    base = ["agent", "--print", "x"]
    assert CursorAuthResolver.augment_command(base) == base


def test_cursor_auth_resolver_skips_whitespace_api_key(monkeypatch):
    monkeypatch.setenv("CURSOR_API_KEY", "   ")
    base = ["agent", "--print", "x"]
    assert CursorAuthResolver.augment_command(base) == base


def test_cursor_auth_resolver_appends_api_key(monkeypatch):
    monkeypatch.setenv("CURSOR_API_KEY", "cursor_secret")
    base = ["agent", "--print", "x"]
    assert CursorAuthResolver.augment_command(base) == base + ["--api-key", "cursor_secret"]


def test_cursor_auth_resolver_does_not_mutate_input(monkeypatch):
    monkeypatch.setenv("CURSOR_API_KEY", "key")
    base = ["agent", "--print", "x"]
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


def test_normalize_mode():
    assert normalize_mode("easy") == MODE_EASY
    assert normalize_mode("simple") == MODE_EASY
    assert normalize_mode("facil") == MODE_EASY
    assert normalize_mode("fácil") == MODE_EASY
    assert normalize_mode("simples") == MODE_EASY
    assert normalize_mode("hard") == MODE_HARD
    assert normalize_mode("complex") == MODE_HARD
    assert normalize_mode("dificil") == MODE_HARD
    assert normalize_mode("difícil") == MODE_HARD
    assert normalize_mode("complexo") == MODE_HARD
    assert normalize_mode("complexa") == MODE_HARD
    assert normalize_mode(None) == DEFAULT_PIPELINE_MODE
    assert normalize_mode("") == DEFAULT_PIPELINE_MODE

    with pytest.raises(ValueError, match="Unknown pipeline mode"):
        normalize_mode("unknown_mode")


def test_resolve_pipeline_config_easy_mode():
    resolved = resolve_pipeline_config("cursor", mode="easy")
    # Easy mode has 6 steps (skips Architect Reviewer)
    assert len(resolved) == 6
    step_names = [s["step_name"] for s in resolved]
    assert "Architect Reviewer (Plan Validation - PLAN)" not in step_names
    assert step_names[0] == "Architect (Planning - PLAN)"
    assert step_names[1] == "Test Developer (Testing - RED)"
    assert step_names[2] == "Developer (Implementation - GREEN)"
    assert step_names[3] == "Code Reviewer (Review - PLAN)"
    assert step_names[4] == "Refactoring Developer (Refactoring - REFACTOR)"
    assert step_names[5] == "GitOps (Documentation and PR)"

    # Code Reviewer in easy mode has medium reasoning budget
    code_reviewer = next(s for s in resolved if s["step_name"] == "Code Reviewer (Review - PLAN)")
    assert code_reviewer["reasoning_budget"] == "medium"


def test_resolve_pipeline_config_hard_mode():
    resolved = resolve_pipeline_config("cursor", mode="hard")
    # Hard mode has all 7 steps (includes Architect Reviewer)
    assert len(resolved) == 7
    step_names = [s["step_name"] for s in resolved]
    assert "Architect Reviewer (Plan Validation - PLAN)" in step_names
    assert step_names[0] == "Architect (Planning - PLAN)"
    assert step_names[1] == "Architect Reviewer (Plan Validation - PLAN)"
    assert step_names[2] == "Test Developer (Testing - RED)"
    assert step_names[3] == "Developer (Implementation - GREEN)"
    assert step_names[4] == "Code Reviewer (Review - PLAN)"
    assert step_names[5] == "Refactoring Developer (Refactoring - REFACTOR)"
    assert step_names[6] == "GitOps (Documentation and PR)"

    step1 = resolved[1]
    assert step1["model"] == "gemini-3.1-pro"
    assert step1["reasoning_budget"] == "high"
    assert "architect_plan.md" in step1["prompt"]
    assert "architect_abort.txt" in step1["prompt"]

    # Code Reviewer in hard mode has high reasoning budget
    code_reviewer = next(s for s in resolved if s["step_name"] == "Code Reviewer (Review - PLAN)")
    assert code_reviewer["reasoning_budget"] == "high"


def test_resolve_pipeline_config_preserves_step_metadata():
    resolved = resolve_pipeline_config("cursor", mode="hard")
    step0 = resolved[0]
    assert step0["step_name"] == "Architect (Planning - PLAN)"
    assert step0["model"] == "gemini-3.7-flash"
    assert "{demand}" in step0["prompt"]

    step1 = resolved[1]
    assert step1["step_name"] == "Architect Reviewer (Plan Validation - PLAN)"
    assert step1["model"] == "gemini-3.1-pro"
    assert step1["reasoning_budget"] == "high"
    assert "architect_plan.md" in step1["prompt"]
    assert "architect_abort.txt" in step1["prompt"]


def test_resolve_review_pipeline_config_explicit_tool():
    resolved = resolve_review_pipeline_config("claude")
    assert len(resolved) == 1
    assert resolved[0]["tool"] == "claude"
    assert resolved[0]["step_name"] == "PR Reviewer"
    assert resolved[0]["timeout"] == "5m"
    assert "{pr_number}" in resolved[0]["prompt"]
    assert "{pr_context}" in resolved[0]["prompt"]


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
        assert "Gemini 3.7 Flash (Low)" in cmd


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
        assert cmd[cmd.index("--model") + 1] == "cursor-grok-4.5-high"


def test_get_model_quota_summary_empty_when_tool_has_no_quota():
    with patch("telegram_listener.DEFAULT_AGENT_TOOL", "cursor"):
        assert get_model_quota_summary() == ""
