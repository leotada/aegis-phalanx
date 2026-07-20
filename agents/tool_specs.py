from dataclasses import dataclass


@dataclass(frozen=True)
class ToolSpec:
    """Infrastructure and runtime metadata for an agent CLI tool."""

    name: str
    install_commands: tuple[str, ...]
    volume_mounts: tuple[tuple[str, str], ...]
    optional_env_vars: tuple[str, ...] = ()
    supports_quota: bool = False


# Mounts required regardless of the active agent tool.
SHARED_VOLUME_MOUNTS: tuple[tuple[str, str], ...] = (
    ("~/.config/aegis-phalanx", "/root/.config/aegis-phalanx"),
    ("~/.config/gh", "/root/.config/gh"),
)

TOOL_SPECS: dict[str, ToolSpec] = {
    "agy": ToolSpec(
        name="agy",
        install_commands=(
            "curl -fsSL https://antigravity.google/cli/install.sh | bash",
        ),
        volume_mounts=(
            ("~/.config/antigravity", "/root/.config/antigravity"),
            ("~/.gemini/antigravity", "/root/.gemini/antigravity"),
            ("~/.gemini/antigravity-cli", "/root/.gemini/antigravity-cli"),
            ("~/.antigravity", "/root/.antigravity"),
        ),
        supports_quota=True,
    ),
    "claude": ToolSpec(
        name="claude",
        install_commands=(
            "npm install -g @anthropic-ai/claude-code",
        ),
        volume_mounts=(
            ("~/.claude", "/root/.claude"),
            ("~/.claude.json", "/root/.claude.json"),
        ),
    ),
    "cursor": ToolSpec(
        name="cursor",
        install_commands=(
            "curl -fsSL https://cursor.com/install | bash",
        ),
        volume_mounts=(
            ("~/.cursor", "/root/.cursor"),
            ("~/.config/Cursor", "/root/.config/Cursor"),
        ),
        optional_env_vars=("CURSOR_API_KEY",),
    ),
    "aider": ToolSpec(
        name="aider",
        install_commands=(
            "pip install --no-cache-dir aider-chat",
        ),
        volume_mounts=(),
    ),
}

DEFAULT_TOOL = "agy"


def get_registered_tools() -> tuple[str, ...]:
    return tuple(TOOL_SPECS.keys())


def validate_tool(tool: str) -> str:
    normalized = (tool or DEFAULT_TOOL).strip().lower()
    if normalized not in TOOL_SPECS:
        allowed = ", ".join(get_registered_tools())
        raise ValueError(f"Unknown AGENT_TOOL '{tool}'. Allowed values: {allowed}")
    return normalized


def get_tool_spec(tool: str | None = None) -> ToolSpec:
    normalized = validate_tool(tool or DEFAULT_TOOL)
    return TOOL_SPECS[normalized]


def get_volume_mounts(tool: str | None = None) -> list[tuple[str, str]]:
    spec = get_tool_spec(tool)
    return list(SHARED_VOLUME_MOUNTS) + list(spec.volume_mounts)
