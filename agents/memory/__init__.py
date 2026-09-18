"""Optional orchestrator-owned ai-memory middleware.

The pipeline never depends on agent CLIs (`agy`, `claude`, …) calling MCP
tools. When `AI_MEMORY_ENABLED` is on and the `ai-memory` binary is present,
the orchestrator injects a bounded wiki/search snapshot and writes progress
pages. Failures are fail-open. Usage is off by default.
"""

from agents.config import env_float, env_int
from agents.memory.manager import AIMemoryManager
from agents.memory.protocol import DisabledMemoryManager, MemoryMiddleware
from agents.memory.settings import (
    DEFAULT_BINARY,
    DEFAULT_CLI_TIMEOUT,
    DEFAULT_CONTEXT_CHARS,
    DEFAULT_DATA_DIR,
    DEFAULT_SERVER_URL,
    DEFAULT_WORKSPACE,
    MEMORY_PREAMBLE,
    PROGRESS_PAGE_PATH,
    SEARCH_HIT_LIMIT,
    ai_memory_binary,
    is_ai_memory_available,
    is_ai_memory_enabled,
    is_ai_memory_requested,
    memory_status_label,
)
from agents.memory.text import clip_text, format_search_hits, project_slug

__all__ = [
    "AIMemoryManager",
    "DEFAULT_BINARY",
    "DEFAULT_CLI_TIMEOUT",
    "DEFAULT_CONTEXT_CHARS",
    "DEFAULT_DATA_DIR",
    "DEFAULT_SERVER_URL",
    "DEFAULT_WORKSPACE",
    "DisabledMemoryManager",
    "MEMORY_PREAMBLE",
    "MemoryMiddleware",
    "PROGRESS_PAGE_PATH",
    "SEARCH_HIT_LIMIT",
    "ai_memory_binary",
    "clip_text",
    "env_float",
    "env_int",
    "format_search_hits",
    "is_ai_memory_available",
    "is_ai_memory_enabled",
    "is_ai_memory_requested",
    "memory_status_label",
    "project_slug",
]
