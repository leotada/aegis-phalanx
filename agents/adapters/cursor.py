from typing import List

from agents.auth.cursor import CursorAuthResolver
from agents.base import AgentCLI

CURSOR_DEFAULT_MODEL = "auto"


class CursorAgentCLI(AgentCLI):
    """
    Adapter for the official Cursor CLI (`agent`).

    Always uses model `auto` regardless of pipeline model/reasoning settings.
    Auth is session-first via mounted host credentials; CURSOR_API_KEY is optional.
    PR reviews use `--mode ask` (read-only) instead of `--force`.
    """

    def build_command(
        self,
        prompt: str,
        model: str,
        reasoning_budget: str,
        timeout: str = None,
        read_only: bool = False,
    ) -> List[str]:
        command = [
            "agent",
            "--print",
            "--model", CURSOR_DEFAULT_MODEL,
            "--trust",
        ]
        if read_only:
            command.extend(["--mode", "ask"])
        else:
            command.append("--force")
        command.append(prompt)
        return CursorAuthResolver.augment_command(command)
