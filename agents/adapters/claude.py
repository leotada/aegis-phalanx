from typing import List

from agents.base import AgentCLI


class ClaudeCodeAgentCLI(AgentCLI):
    """Adapter for the official Claude Code CLI (Anthropic)."""

    def build_command(
        self,
        prompt: str,
        model: str,
        reasoning_budget: str,
        timeout: str = None,
    ) -> List[str]:
        return [
            "claude",
            "-p", prompt,
            "-y",
        ]
