"""GitHub repository URL normalization and owner/repo extraction."""

from __future__ import annotations

import re


class RepoUrls:
    """Normalizes GitHub repository URLs and extracts the owner/repo slug."""

    def normalize(self, repo: str) -> str:
        """Normalizes any repo format, preserving SSH/HTTPS protocols, ending with .git."""
        repo = repo.strip()

        # Check if it starts with SSH URL format
        # E.g. git@github.com:owner/repo or ssh://git@github.com/owner/repo
        ssh_prefix_match = re.match(r'^(?:ssh://)?git@github\.com[:/](.*)$', repo, re.IGNORECASE)
        if ssh_prefix_match:
            repo_path = ssh_prefix_match.group(1)
            if repo_path.lower().endswith(".git"):
                repo_path = repo_path[:-4]
            return f"git@github.com:{repo_path}.git"

        # Check if it starts with HTTP/HTTPS URL
        if repo.lower().startswith(("http://", "https://")):
            if repo.lower().endswith(".git"):
                repo = repo[:-4]
            return f"{repo}.git"

        # Shorthand (owner/repo)
        if repo.lower().endswith(".git"):
            repo = repo[:-4]
        return f"https://github.com/{repo}.git"

    def owner_repo(self, repo_url: str) -> str | None:
        """
        Extracts the 'owner/repo' slug from any supported GitHub URL format.
        Returns None if the URL cannot be parsed.
        Supported formats:
          - git@github.com:owner/repo.git
          - https://github.com/owner/repo.git
          - https://x-access-token:<token>@github.com/owner/repo.git
        """
        # SSH format: git@github.com:owner/repo or git@github.com:owner/repo.git
        ssh_match = re.match(
            r'^(?:ssh://)?git@github\.com[:/]([a-zA-Z0-9_\-]+/[a-zA-Z0-9_\-\.]+?)(?:\.git)?$',
            repo_url.strip(),
            re.IGNORECASE,
        )
        if ssh_match:
            return ssh_match.group(1)

        # HTTPS format (with optional token auth): https://[token@]github.com/owner/repo[.git]
        https_match = re.match(
            r'^https?://(?:[^@/]+@)?github\.com/([a-zA-Z0-9_\-]+/[a-zA-Z0-9_\-\.]+?)(?:\.git)?$',
            repo_url.strip(),
            re.IGNORECASE,
        )
        if https_match:
            return https_match.group(1)

        return None


repo_urls = RepoUrls()
