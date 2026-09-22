"""Git status, pytest summary, and current-branch PR URL helpers."""

from __future__ import annotations

import re
import subprocess

from orchestrator.paths import PROJECT_DIR


def get_git_changes() -> str:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=PROJECT_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        if result.returncode == 0 and result.stdout.strip():
            lines = result.stdout.strip().splitlines()
            changes = []
            for line in lines[:5]:
                parts = line.strip().split(maxsplit=1)
                if len(parts) == 2:
                    status, path = parts
                    changes.append(f"• `{path}` ({status})")
            if len(lines) > 5:
                changes.append(f"• ... and {len(lines) - 5} more files")
            return "\n".join(changes)
    except Exception:
        pass
    return ""


def get_pytest_summary(output: str) -> str:
    # Match standard pytest summary patterns
    match = re.search(r'=+\s+([\d\s\w\-,]+)\s+in\s+[\d\.]+s\s+=+', output)
    if match:
        return match.group(1).strip()
    match2 = re.search(r'([\d]+ passed, [\d]+ failed.*)', output)
    if match2:
        return match2.group(1).strip()
    return ""


def get_pr_url() -> str:
    """Uses the GitHub CLI to get the PR URL for the current branch, if one exists."""
    try:
        result = subprocess.run(
            ["gh", "pr", "view", "--json", "url", "-q", ".url"],
            cwd=PROJECT_DIR,
            capture_output=True,
            text=True,
            check=False
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    return ""
