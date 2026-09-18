from agents.adapters.agy import AntigravityAgentCLI
from agents.adapters.aider import AiderAgentCLI
from agents.adapters.claude import ClaudeCodeAgentCLI
from agents.adapters.cursor import CursorAgentCLI
from agents.base import AgentCLI
from agents.config import AGENT_INTENT_TIMEOUT, AGENT_STEP_TIMEOUT, DEFAULT_AGENT_TOOL, env_flag
from agents.memory_manager import (
    get_memory_manager,
    is_ai_memory_enabled,
    memory_status_label,
    reset_memory_manager_cache,
)
from agents.pipeline import (
    DEFAULT_PIPELINE_MODE,
    MODE_EASY,
    MODE_HARD,
    PIPELINE_CONFIG,
    normalize_mode,
    resolve_pipeline_config,
)
from agents.review_pipeline import PR_REVIEW_CONFIG, resolve_review_pipeline_config
from agents.registry import AgentRegistry
from agents.tool_specs import get_registered_tools, get_tool_spec, validate_tool


def register_defaults() -> None:
    AgentRegistry.register("agy", AntigravityAgentCLI)
    AgentRegistry.register("claude", ClaudeCodeAgentCLI)
    AgentRegistry.register("aider", AiderAgentCLI)
    AgentRegistry.register("cursor", CursorAgentCLI)


register_defaults()

__all__ = [
    "AgentCLI",
    "AgentRegistry",
    "AntigravityAgentCLI",
    "AiderAgentCLI",
    "ClaudeCodeAgentCLI",
    "CursorAgentCLI",
    "AGENT_STEP_TIMEOUT",
    "AGENT_INTENT_TIMEOUT",
    "DEFAULT_AGENT_TOOL",
    "DEFAULT_PIPELINE_MODE",
    "MODE_EASY",
    "MODE_HARD",
    "normalize_mode",
    "PIPELINE_CONFIG",
    "resolve_pipeline_config",
    "PR_REVIEW_CONFIG",
    "resolve_review_pipeline_config",
    "get_registered_tools",
    "get_tool_spec",
    "validate_tool",
    "env_flag",
    "get_memory_manager",
    "is_ai_memory_enabled",
    "memory_status_label",
    "reset_memory_manager_cache",
]
