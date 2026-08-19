from typing import List

from agents.base import AgentCLI
from agents.config import AGENT_STEP_TIMEOUT


AGY_DEFAULT_MODEL = "gemini-3.7-flash"
AGY_DEFAULT_EFFORT = "medium"


class AntigravityAgentCLI(AgentCLI):
    """Adapter for the official Antigravity CLI (Google)."""

    def build_command(
        self,
        prompt: str,
        model: str,
        reasoning_budget: str,
        timeout: str = None,
        read_only: bool = False,
    ) -> List[str]:
        model_map = {
            "gemini-3.1-pro": "Gemini 3.1 Pro",
            "gemini-3.5-flash": "Gemini 3.5 Flash",
            "gemini-3.6-flash": "Gemini 3.6 Flash",
            "gemini-3.7-pro": "Gemini 3.7 Pro",
            "gemini-3.7-flash": "Gemini 3.7 Flash",
        }

        resolved_model = (model or AGY_DEFAULT_MODEL).strip()
        base_name = model_map.get(resolved_model.lower(), resolved_model)
        budget = (reasoning_budget or AGY_DEFAULT_EFFORT).capitalize()
        full_model_name = f"{base_name} ({budget})"
        effective_timeout = timeout if timeout else AGENT_STEP_TIMEOUT

        return [
            "agy",
            "--model", full_model_name,
            "--dangerously-skip-permissions",
            "--print-timeout", effective_timeout,
            "--print", prompt,
        ]
