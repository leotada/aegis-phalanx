from typing import List

from agents.auth.cursor import CursorAuthResolver
from agents.base import AgentCLI

CURSOR_DEFAULT_MODEL = "auto"


class CursorAgentCLI(AgentCLI):
    """
    Adapter for the official Cursor CLI (`agent`).

    Always uses model `auto` regardless of pipeline model/reasoning settings.
    Auth is session-first via mounted host credentials; CURSOR_API_KEY is optional.
    """

    def build_command(
        self,
        prompt: str,
        model: str,
        reasoning_budget: str,
        timeout: str = None,
    ) -> List[str]:
        command = [
            "agent",
            "-p", prompt,
            "--model", CURSOR_DEFAULT_MODEL,
            "--trust",
            "--force",
        ]
        return CursorAuthResolver.augment_command(command)
