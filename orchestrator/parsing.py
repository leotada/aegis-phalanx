"""Parse user demand text: repo URLs, pipeline mode, and PR references."""

from __future__ import annotations

import re

from agents.pipeline import MODE_EASY, MODE_HARD
from orchestrator.urls import normalize_repo_url


def parse_demand(demand: str, default_repo: str = None, last_repo: str = None) -> tuple[str, str]:
    """
    Parses the user's demand to extract the repository URL and the clean demand description.
    """
    demand_stripped = demand.strip()

    # 1. Search for full HTTP/HTTPS or SSH Github URLs anywhere in the string
    url_pattern = r'(?:https?://github\.com/|(?:ssh://)?git@github\.com[:/])[a-zA-Z0-9_\-]+/[a-zA-Z0-9_\-\.]+(?:\.git)?'
    url_match = re.search(url_pattern, demand_stripped, re.IGNORECASE)
    if url_match:
        repo_url = url_match.group(0)
        start_idx, end_idx = url_match.span()

        left_part = demand_stripped[:start_idx]
        right_part = demand_stripped[end_idx:]

        # Clean colons/dashes/dots right after the URL
        right_part = re.sub(r'^\s*[:\-.,;]\s*', '', right_part)
        # Clean demand/task prefix in right_part if present
        right_part = re.sub(
            r'^\s*(?:demanda|demand|task|tarefa|descri[cç][aã]o|description)\s*[:\-.,;]?\s*',
            '',
            right_part,
            flags=re.IGNORECASE,
        )

        # Clean colons/dashes/dots right before the URL
        left_part = re.sub(r'\s*[:\-.,;]\s*$', '', left_part)

        # Clean repository keywords and prepositions before the URL
        left_part = re.sub(
            r'(?:\b(?:no|na|do|da|em|para\s+o|para\s+a|para|de|in|for|on|to|at|into|from|of)\s+)?\b(?:reposit[oó]rios?|repos?|repository|repositories)\b\s*$',
            '',
            left_part,
            flags=re.IGNORECASE,
        )
        # Clean prepositions before the URL
        left_part = re.sub(
            r'\b(in|for|on|to|at|into|from|no|na|do|da|em|para|de)\s*$',
            '',
            left_part,
            flags=re.IGNORECASE,
        )
        left_part = re.sub(r'\s*[:\-.,;]\s*$', '', left_part)

        clean_demand = (left_part.strip() + " " + right_part.strip()).strip()
        return normalize_repo_url(repo_url), clean_demand

    # Clean leading repo label if present before shorthand or text
    shorthand_cleaned = re.sub(
        r'^(?:(?:no|na|do|da|em|para\s+o|para\s+a|para|de|in|for|on|to|at|into|from|of)\s+)?\b(?:reposit[oó]rios?|repos?|repository|repositories)\b\s*[:\-.,;]?\s*',
        '',
        demand_stripped,
        flags=re.IGNORECASE,
    )

    # 2. Match shorthand owner/repo followed by a colon or separator at the start of the message
    shorthand_colon_match = re.match(
        r'^([a-zA-Z0-9_\-]+/[a-zA-Z0-9_\-\.]+?)(?:\.git)?\s*[:\-]\s*(.*)$',
        shorthand_cleaned,
        re.IGNORECASE,
    )
    if shorthand_colon_match:
        repo_name = shorthand_colon_match.group(1)
        clean_demand = shorthand_colon_match.group(2).strip()
        clean_demand = re.sub(
            r'^(?:demanda|demand|task|tarefa|descri[cç][aã]o|description)\s*[:\-.,;]?\s*',
            '',
            clean_demand,
            flags=re.IGNORECASE,
        ).strip()
        return normalize_repo_url(repo_name), clean_demand

    # 3. Match shorthand owner/repo by itself (entire string)
    shorthand_exact_match = re.match(
        r'^([a-zA-Z0-9_\-]+/[a-zA-Z0-9_\-\.]+?)(?:\.git)?$',
        shorthand_cleaned,
        re.IGNORECASE,
    )
    if shorthand_exact_match:
        repo_name = shorthand_exact_match.group(1)
        return normalize_repo_url(repo_name), ""

    # Fallbacks
    if default_repo:
        return normalize_repo_url(default_repo), demand

    if last_repo:
        return normalize_repo_url(last_repo), demand

    return None, demand


def extract_pipeline_mode(text: str) -> tuple[str, str]:
    """
    Extracts the execution mode ('easy' or 'hard') from user input and returns (cleaned_text, mode).
    Defaults to 'easy' if no mode indicator is present.
    """
    if not isinstance(text, str):
        text = str(text) if text is not None else ""
    if not text:
        return text, MODE_EASY

    hard_patterns = [
        r'\[(?:hard|complex|dif[ií]cil|complex[oa])\]',
        r'\((?:hard|complex|dif[ií]cil|complex[oa])\)',
        r'--+(?:hard|complex|dif[ií]cil|complex[oa])\b',
        r'\b(?:tarefa|modo|task|mode)\s*[:\-]?\s*(?:dif[ií]cil|dificil|hard|complex[oa]|complex)\b\s*[:\-.,;]?\s*',
        r'\b(?:dif[ií]cil|dificil|hard|complex[oa]|complex)\s+(?:tarefa|modo|task|mode)\b\s*[:\-.,;]?\s*',
        r'(?:^|[\n\r])\s*(?:hard|dif[ií]cil|dificil|complex[oa]|complex)\s*[:\-.,;]?\s*(?:[\n\r]|$)',
        r'\b(?:hard|dif[ií]cil|dificil|complex[oa]|complex)\s*[:\-.,;]\s*',
    ]

    easy_patterns = [
        r'\[(?:easy|simple|f[aá]cil|facil|simples)\]',
        r'\((?:easy|simple|f[aá]cil|facil|simples)\)',
        r'--+(?:easy|simple|f[aá]cil|facil|simples)\b',
        r'\b(?:tarefa|modo|task|mode)\s*[:\-]?\s*(?:f[aá]cil|facil|simples|easy|simple)\b\s*[:\-.,;]?\s*',
        r'\b(?:f[aá]cil|facil|simples|easy|simple)\s+(?:tarefa|modo|task|mode)\b\s*[:\-.,;]?\s*',
        r'(?:^|[\n\r])\s*(?:easy|f[aá]cil|facil|simples|simple)\s*[:\-.,;]?\s*(?:[\n\r]|$)',
        r'\b(?:easy|f[aá]cil|facil|simples|simple)\s*[:\-.,;]\s*',
    ]

    detected_mode = None
    cleaned = text

    for pattern in hard_patterns:
        match = re.search(pattern, cleaned, re.IGNORECASE)
        if match:
            detected_mode = MODE_HARD
            start, end = match.span()
            left = cleaned[:start].rstrip()
            right = cleaned[end:].lstrip()
            right = re.sub(r'^[\s:\-.,;]+', '', right)
            cleaned = (left + " " + right).strip() if left and right else (left or right).strip()
            break

    if not detected_mode:
        for pattern in easy_patterns:
            match = re.search(pattern, cleaned, re.IGNORECASE)
            if match:
                detected_mode = MODE_EASY
                start, end = match.span()
                left = cleaned[:start].rstrip()
                right = cleaned[end:].lstrip()
                right = re.sub(r'^[\s:\-.,;]+', '', right)
                cleaned = (left + " " + right).strip() if left and right else (left or right).strip()
                break

    mode = detected_mode if detected_mode else MODE_EASY
    return cleaned, mode


def parse_pr_reference(text: str, default_repo: str = None) -> tuple[str | None, int | None]:
    """
    Parses a PR reference from user input.
    Supported formats:
      - owner/repo#123
      - owner/repo:123 or owner/repo 123
      - https://github.com/owner/repo/pull/123
      - #123 or 123 (requires default_repo)
    Returns (repo_url, pr_number) or (None, None) if unparseable.
    """
    cleaned = re.sub(r"^/review\s*", "", text.strip(), flags=re.IGNORECASE).strip()

    url_match = re.search(
        r"https?://github\.com/([a-zA-Z0-9_\-]+/[a-zA-Z0-9_\-\.]+)/pull/(\d+)",
        cleaned,
        re.IGNORECASE,
    )
    if url_match:
        return normalize_repo_url(url_match.group(1)), int(url_match.group(2))

    hash_match = re.match(
        r"^([a-zA-Z0-9_\-]+/[a-zA-Z0-9_\-\.]+?)#(\d+)$",
        cleaned,
        re.IGNORECASE,
    )
    if hash_match:
        return normalize_repo_url(hash_match.group(1)), int(hash_match.group(2))

    sep_match = re.match(
        r"^([a-zA-Z0-9_\-]+/[a-zA-Z0-9_\-\.]+?)\s*[:\s]\s*(\d+)$",
        cleaned,
        re.IGNORECASE,
    )
    if sep_match:
        return normalize_repo_url(sep_match.group(1)), int(sep_match.group(2))

    num_match = re.match(r"^#?(\d+)$", cleaned)
    if num_match and default_repo:
        return normalize_repo_url(default_repo), int(num_match.group(1))

    return None, None
