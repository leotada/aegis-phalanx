import os
from typing import List


class CursorAuthResolver:
    """
    Resolves Cursor CLI authentication arguments.

    Session auth (from `agent login` on the host, mounted into the container)
    is preferred. When CURSOR_API_KEY is set, it is passed explicitly as a
    fallback for headless or CI environments.
    """

    @staticmethod
    def augment_command(command: List[str]) -> List[str]:
        api_key = os.environ.get("CURSOR_API_KEY", "").strip()
        if not api_key:
            return command
        return command + ["--api-key", api_key]
