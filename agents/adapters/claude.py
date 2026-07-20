from typing import List

from agents.base import AgentCLI

# Pipeline defaults use Gemini slugs; map them to Claude Code aliases.
# Explicit Claude aliases / full model names are passed through unchanged.
CLAUDE_MODEL_MAP = {
    "gemini-3.1-pro": "opus",
    "gemini-3.5-flash": "sonnet",
}

CLAUDE_EFFORT_LEVELS = frozenset({"low", "medium", "high", "xhigh", "max"})
CLAUDE_DEFAULT_MODEL = "sonnet"
CLAUDE_DEFAULT_EFFORT = "medium"


class ClaudeCodeAgentCLI(AgentCLI):
    """
    Adapter for the official Claude Code CLI (`claude`).

    Uses non-interactive `--print` mode. Write steps bypass permission prompts
    with `--dangerously-skip-permissions` (sandbox). PR reviews use
    `--permission-mode plan` (read-only). Maps pipeline Gemini model slugs to
    Claude aliases and passes `reasoning_budget` as `--effort`.
    """

    def build_command(
        self,
        prompt: str,
        model: str,
        reasoning_budget: str,
        timeout: str = None,
        read_only: bool = False,
    ) -> List[str]:
        resolved_model = CLAUDE_DEFAULT_MODEL
        if model:
            resolved_model = CLAUDE_MODEL_MAP.get(model.lower(), model)

        effort = (reasoning_budget or CLAUDE_DEFAULT_EFFORT).lower()
        if effort not in CLAUDE_EFFORT_LEVELS:
            effort = CLAUDE_DEFAULT_EFFORT

        command = [
            "claude",
            "--print",
            "--model", resolved_model,
            "--effort", effort,
        ]
        if read_only:
            command.extend(["--permission-mode", "plan"])
        else:
            command.append("--dangerously-skip-permissions")
        command.append(prompt)
        return command
