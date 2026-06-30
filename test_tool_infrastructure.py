import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from agents.tool_specs import (
    get_registered_tools,
    get_tool_spec,
    get_volume_mounts,
    validate_tool,
)


def test_validate_tool_accepts_registered_tools():
    for tool in get_registered_tools():
        assert validate_tool(tool) == tool


def test_validate_tool_rejects_unknown():
    with pytest.raises(ValueError, match="Unknown AGENT_TOOL"):
        validate_tool("unknown-cli")


def test_get_volume_mounts_include_shared_and_tool_specific():
    mounts = get_volume_mounts("agy")
    hosts = [host for host, _ in mounts]
    assert "~/.config/aegis-phalanx" in hosts
    assert "~/.config/gh" in hosts
    assert "~/.config/antigravity" in hosts


def test_get_volume_mounts_claude_only_has_claude_sessions():
    mounts = get_volume_mounts("claude")
    hosts = [host for host, _ in mounts]
    assert "~/.config/claude" in hosts
    assert "~/.config/antigravity" not in hosts


def test_aider_spec_has_no_extra_volume_mounts():
    spec = get_tool_spec("aider")
    assert spec.volume_mounts == ()
    assert spec.optional_env_vars == ()


def test_cursor_spec_has_optional_env_and_no_quota():
    spec = get_tool_spec("cursor")
    assert "CURSOR_API_KEY" in spec.optional_env_vars
    assert spec.supports_quota is False


def test_agy_spec_supports_quota():
    assert get_tool_spec("agy").supports_quota is True


def test_all_specs_define_install_commands():
    for tool in get_registered_tools():
        spec = get_tool_spec(tool)
        assert spec.install_commands, f"{tool} must define install_commands"


@pytest.mark.parametrize("tool,expected_host", [
    ("agy", "~/.config/antigravity"),
    ("claude", "~/.config/claude"),
    ("cursor", "~/.cursor"),
])
def test_render_compose_overlay_includes_tool_mounts(tool, expected_host, monkeypatch):
    monkeypatch.setenv("AGENT_TOOL", tool)
    repo_root = Path(__file__).resolve().parent
    script = repo_root / "scripts" / "render_compose_overlay.py"
    generated = repo_root / "compose.tool.yml"

    if generated.exists():
        generated.unlink()

    subprocess.run([sys.executable, str(script)], cwd=repo_root, check=True)
    content = generated.read_text(encoding="utf-8")

    assert f"AGENT_TOOL={tool}" in content
    assert expected_host in content
    assert "~/.config/aegis-phalanx" in content

    generated.unlink()


def test_render_compose_overlay_omits_env_for_agy(monkeypatch):
    monkeypatch.setenv("AGENT_TOOL", "agy")
    repo_root = Path(__file__).resolve().parent
    script = repo_root / "scripts" / "render_compose_overlay.py"
    generated = repo_root / "compose.tool.yml"

    if generated.exists():
        generated.unlink()

    subprocess.run([sys.executable, str(script)], cwd=repo_root, check=True)
    content = generated.read_text(encoding="utf-8")

    assert "environment:" not in content
    generated.unlink()


def test_install_agent_tool_runs_spec_commands(monkeypatch):
    monkeypatch.setenv("AGENT_TOOL", "claude")
    repo_root = Path(__file__).resolve().parent
    script = repo_root / "scripts" / "install_agent_tool.py"

    with patch("subprocess.run") as mock_run:
        import runpy
        runpy.run_path(str(script), run_name="__main__")
        commands = [call.args[0] for call in mock_run.call_args_list]
        assert any("claude-code" in cmd for cmd in commands)


def test_install_agent_tool_rejects_unknown_tool(monkeypatch):
    monkeypatch.setenv("AGENT_TOOL", "not-a-real-tool")
    repo_root = Path(__file__).resolve().parent
    script = repo_root / "scripts" / "install_agent_tool.py"

    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "Unknown AGENT_TOOL" in result.stderr + result.stdout
