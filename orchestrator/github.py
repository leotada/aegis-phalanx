"""Resolve an authenticated git clone URL (token, gh CLI, or SSH)."""

from __future__ import annotations

import asyncio
import shutil

from orchestrator.urls import extract_owner_repo


async def _gh_auth_token() -> str | None:
    """Returns a token from an authenticated gh CLI, or None if unavailable."""
    if shutil.which("gh") is None:
        return None
    try:
        proc = await asyncio.create_subprocess_exec(
            "gh", "auth", "token",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await proc.communicate()
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    token = out.decode("utf-8", errors="replace").strip()
    return token or None


async def _ssh_github_available() -> bool:
    """Checks whether an SSH key can authenticate against github.com (non-interactively)."""
    if shutil.which("ssh") is None:
        return False
    try:
        proc = await asyncio.create_subprocess_exec(
            "ssh", "-T",
            "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", "ConnectTimeout=10",
            "git@github.com",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()
    except Exception:
        return False
    # GitHub always closes the shell (exit 1) but greets authenticated users.
    output = (out + err).decode("utf-8", errors="replace").lower()
    return "successfully authenticated" in output


async def resolve_clone_url(
    repo_url: str,
    github_token: str | None,
    *,
    gh_token_fn=None,
    ssh_available_fn=None,
) -> tuple[str | None, str, str | None]:
    """
    Resolves the best authenticated clone URL for a GitHub repository.

    Returns a tuple of (clone_url, method, error). When error is not None,
    clone_url is None and no credentials could be resolved.

    Credential preference for HTTPS GitHub URLs: GITHUB_TOKEN -> gh CLI -> SSH key.
    Already-SSH URLs and non-GitHub URLs are returned unchanged.
    """
    if not repo_url:
        return repo_url, "as-is", None

    # SSH URLs rely on the local SSH key/agent; use them unchanged.
    if repo_url.startswith("git@") or repo_url.startswith("ssh://"):
        return repo_url, "ssh", None

    if not repo_url.startswith("https://github.com/"):
        # Non-GitHub HTTPS (or other) URL: leave it to git's own credential handling.
        return repo_url, "as-is", None

    def _with_token(token: str) -> str:
        return repo_url.replace(
            "https://github.com/", f"https://x-access-token:{token}@github.com/"
        )

    # 1. Explicit token (existing behavior).
    if github_token:
        return _with_token(github_token), "github-token", None

    # 2. gh CLI credentials (preferred fallback).
    get_gh_token = gh_token_fn or _gh_auth_token
    gh_token = await get_gh_token()
    if gh_token:
        return _with_token(gh_token), "gh-cli", None

    # 3. SSH key fallback.
    check_ssh = ssh_available_fn or _ssh_github_available
    owner_repo = extract_owner_repo(repo_url)
    if owner_repo and await check_ssh():
        return f"git@github.com:{owner_repo}.git", "ssh", None

    return (
        None,
        "none",
        "No GitHub credentials available. Set GITHUB_TOKEN, authenticate the gh CLI "
        "(<code>gh auth login</code>), or configure an SSH key for github.com.",
    )
