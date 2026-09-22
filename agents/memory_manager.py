"""Public factory for optional ai-memory middleware.

Implementation lives in `agents.memory`. This module remains the import path
used by the orchestrator and tests.
"""

from __future__ import annotations

import atexit

from agents.memory import (
    AIMemoryManager,
    DEFAULT_BINARY,
    DEFAULT_CLI_TIMEOUT,
    DEFAULT_CONTEXT_CHARS,
    DEFAULT_DATA_DIR,
    DEFAULT_SERVER_URL,
    DEFAULT_WORKSPACE,
    DisabledMemoryManager,
    MEMORY_PREAMBLE,
    MemoryMiddleware,
    PROGRESS_PAGE_PATH,
    REVIEW_PAGE_PATH,
    SEARCH_HIT_LIMIT,
    ai_memory_binary,
    clip_text,
    env_float,
    env_int,
    format_search_hits,
    is_ai_memory_available,
    is_ai_memory_enabled,
    is_ai_memory_requested,
    memory_status_label,
    project_slug,
)

_CACHED_MANAGER: MemoryMiddleware | None = None
_MISSING_BINARY_WARNED = False


def _stop_cached_serve() -> None:
    manager = _CACHED_MANAGER
    stop = getattr(manager, "stop_serve", None)
    if stop is not None:
        stop()


def reset_memory_manager_cache() -> None:
    """Drops the cached live manager (tests and process shutdown)."""
    global _CACHED_MANAGER, _MISSING_BINARY_WARNED
    manager = _CACHED_MANAGER
    _CACHED_MANAGER = None
    _MISSING_BINARY_WARNED = False
    stop = getattr(manager, "stop_serve", None)
    if stop is not None:
        stop()


atexit.register(_stop_cached_serve)


def get_memory_manager() -> MemoryMiddleware:
    """Returns a live manager when enabled, otherwise a no-op middleware."""
    global _CACHED_MANAGER, _MISSING_BINARY_WARNED
    if not is_ai_memory_requested():
        return DisabledMemoryManager()
    if not is_ai_memory_available():
        if not _MISSING_BINARY_WARNED:
            print(
                "AI_MEMORY_ENABLED is set but the ai-memory binary was not found; "
                "pipeline memory hooks are skipped.",
                flush=True,
            )
            _MISSING_BINARY_WARNED = True
        return DisabledMemoryManager()
    if _CACHED_MANAGER is None:
        _CACHED_MANAGER = AIMemoryManager()
    return _CACHED_MANAGER


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
    "REVIEW_PAGE_PATH",
    "SEARCH_HIT_LIMIT",
    "ai_memory_binary",
    "clip_text",
    "env_float",
    "env_int",
    "format_search_hits",
    "get_memory_manager",
    "is_ai_memory_available",
    "is_ai_memory_enabled",
    "is_ai_memory_requested",
    "memory_status_label",
    "project_slug",
    "reset_memory_manager_cache",
]
