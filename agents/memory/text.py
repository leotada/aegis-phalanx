"""Pure text helpers for wiki slugs, clipping, and search rendering."""

from __future__ import annotations

import json
import re


def clip_text(text: str, limit: int, ellipsis: str = "\n… (truncated)") -> str:
    if limit <= 0 or len(text) <= limit:
        return text
    keep = max(0, limit - len(ellipsis))
    return text[:keep] + ellipsis


def project_slug(repo_url: str | None, fallback: str = "project") -> str:
    """Turns a repo URL into an ai-memory `--project` name (no slashes)."""
    if not repo_url:
        return fallback
    cleaned = repo_url.strip()
    if cleaned.lower().endswith(".git"):
        cleaned = cleaned[:-4]
    cleaned = cleaned.replace(":", "/")
    parts = [part for part in cleaned.split("/") if part]
    if len(parts) >= 2:
        slug = f"{parts[-2]}-{parts[-1]}"
    elif parts:
        slug = parts[-1]
    else:
        slug = fallback
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", slug).strip("-._").lower()
    return slug or fallback


def format_search_hits(stdout: str) -> str:
    """Renders `ai-memory search --json` output as compact prompt text."""
    raw = (stdout or "").strip()
    if not raw:
        return ""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    if not isinstance(data, list):
        return raw
    lines: list[str] = []
    for hit in data:
        if not isinstance(hit, dict):
            continue
        path = str(hit.get("path") or "").strip()
        title = str(hit.get("title") or "").strip()
        snippet = str(hit.get("snippet") or "").strip()
        label = path or title or "page"
        if title and path:
            label = f"{path} — {title}"
        elif title:
            label = title
        if snippet:
            lines.append(f"- {label}: {snippet}")
        else:
            lines.append(f"- {label}")
    return "\n".join(lines)
