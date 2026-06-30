from typing import List

from agents.base import AgentCLI


class AiderAgentCLI(AgentCLI):
    """Optional adapter for Aider."""

    def build_command(
        self,
        prompt: str,
        model: str,
        reasoning_budget: str,
        timeout: str = None,
    ) -> List[str]:
        return [
            "aider",
            "--model", model,
            "--message", prompt,
            "--yes",
            "--no-auto-commits",
        ]
