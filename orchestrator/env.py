"""Environment sanitization for the bot process."""

import os


def sanitize_environment() -> None:
    """Removes GITHUB_TOKEN if it is set to the default placeholder, empty, or whitespace only."""
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token or token == "your_github_token_here":
        os.environ.pop("GITHUB_TOKEN", None)
