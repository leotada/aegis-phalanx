"""Environment sanitization for the bot process."""

from __future__ import annotations

import os


class Environment:
    """Sanitizes process environment variables before the bot starts."""

    PLACEHOLDER_GITHUB_TOKEN = "your_github_token_here"

    def sanitize(self) -> None:
        """Removes GITHUB_TOKEN if it is set to the default placeholder, empty, or whitespace only."""
        token = os.environ.get("GITHUB_TOKEN", "").strip()
        if not token or token == self.PLACEHOLDER_GITHUB_TOKEN:
            os.environ.pop("GITHUB_TOKEN", None)


environment = Environment()
