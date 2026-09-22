import os

from agents.tool_specs import DEFAULT_TOOL, validate_tool

AGENT_STEP_TIMEOUT = os.environ.get("AGENT_STEP_TIMEOUT", "5m")
AGENT_INTENT_TIMEOUT = os.environ.get("AGENT_INTENT_TIMEOUT", "15s")
DEFAULT_AGENT_TOOL = validate_tool(os.environ.get("AGENT_TOOL", DEFAULT_TOOL))

TRUE_FLAG_VALUES = {"1", "true", "yes", "on"}


def env_flag(name: str, default: bool = False) -> bool:
    """Reads a boolean environment variable. Missing values use *default*."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in TRUE_FLAG_VALUES


def env_int(name: str, default: int) -> int:
    """Reads a positive integer environment variable. Invalid values use *default*."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def env_float(name: str, default: float) -> float:
    """Reads a positive float environment variable. Invalid values use *default*."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default
