from typing import List

from agents.base import AgentCLI
from agents.config import AGENT_STEP_TIMEOUT


class AntigravityAgentCLI(AgentCLI):
    """Adapter for the official Antigravity CLI (Google)."""

    def build_command(
        self,
        prompt: str,
        model: str,
        reasoning_budget: str,
        timeout: str = None,
    ) -> List[str]:
        model_map = {
            "gemini-3.1-pro": "Gemini 3.1 Pro",
            "gemini-3.5-flash": "Gemini 3.5 Flash",
        }

        base_name = model_map.get(model.lower(), model)
        budget = reasoning_budget.capitalize() if reasoning_budget else "Medium"
        full_model_name = f"{base_name} ({budget})"
        effective_timeout = timeout if timeout else AGENT_STEP_TIMEOUT

        return [
            "agy",
            "--model", full_model_name,
            "--dangerously-skip-permissions",
            "--print-timeout", effective_timeout,
            "--print", prompt,
        ]
