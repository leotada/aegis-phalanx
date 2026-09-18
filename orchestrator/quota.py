"""Parse and format agy /usage quota output."""

from __future__ import annotations

import fcntl
import os
import pty
import re
import select
import struct
import subprocess
import termios
import time
from typing import Dict, List

import html


def strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", text)


def capture_agy_quota_output(*, timeout: int, scratch_dir: str) -> str:
    """Runs the agy TUI /usage command via PTY and returns the captured terminal output."""
    os.makedirs(scratch_dir, exist_ok=True)
    rows, cols = 40, 120
    master, slave = pty.openpty()
    winsize = struct.pack("HHHH", rows, cols, 0, 0)
    fcntl.ioctl(slave, termios.TIOCSWINSZ, winsize)
    fcntl.ioctl(master, termios.TIOCSWINSZ, winsize)

    env = os.environ.copy()
    env["TERM"] = "xterm-256color"
    proc = subprocess.Popen(
        ["agy"],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        cwd=scratch_dir,
        close_fds=True,
        env=env,
    )
    os.close(slave)

    chunks: List[str] = []
    deadline = time.time() + timeout
    sent_trust = False
    sent_usage = False
    usage_sent_at = None

    while time.time() < deadline:
        if proc.poll() is not None:
            break
        ready, _, _ = select.select([master], [], [], 0.15)
        if master not in ready:
            continue
        try:
            chunk = os.read(master, 8192)
        except OSError:
            break
        if not chunk:
            break
        chunks.append(chunk.decode("utf-8", errors="replace"))
        plain = strip_ansi("".join(chunks))

        if not sent_trust and "trust" in plain.lower() and "folder" in plain.lower():
            os.write(master, b"\r")
            sent_trust = True
            time.sleep(1.5)

        if not sent_usage and "Antigravity CLI" in plain and ">" in plain:
            time.sleep(1.5)
            os.write(master, b"/usage\r")
            sent_usage = True
            usage_sent_at = time.time()

        if sent_usage and usage_sent_at:
            if "GEMINI MODELS" in plain and "Five Hour Limit" in plain:
                time.sleep(1)
                break
            if time.time() - usage_sent_at > 25:
                break

    try:
        proc.terminate()
        proc.wait(timeout=2)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass

    return strip_ansi("".join(chunks))


def parse_model_quota(text: str) -> Dict[str, Dict[str, Dict[str, float | str]]]:
    """Parses agy /usage output into remaining and usage percentages per model group."""
    result: Dict[str, Dict[str, Dict[str, float | str]]] = {}
    current_group = None
    current_limit = None

    for line in strip_ansi(text).splitlines():
        stripped = line.strip()
        if stripped.endswith("MODELS") and stripped == stripped.upper():
            current_group = stripped
            result.setdefault(current_group, {})
            current_limit = None
            continue
        if stripped in ("Five Hour Limit", "Five-Hour Limit"):
            current_limit = "five_hour"
            continue
        if stripped == "Weekly Limit":
            current_limit = "weekly"
            continue
        if not current_group or not current_limit:
            continue

        remaining_match = re.search(r"(\d+(?:\.\d+)?)%\s+remaining", stripped, re.IGNORECASE)
        bar_match = re.search(r"\]\s*(\d+(?:\.\d+)?)%", stripped)
        refresh_match = re.search(r"Refreshes in\s+(.+)$", stripped, re.IGNORECASE)

        if remaining_match or bar_match:
            remaining = float(
                remaining_match.group(1) if remaining_match else bar_match.group(1)
            )
            entry = result[current_group].setdefault(current_limit, {})
            entry["remaining"] = remaining
            entry["usage"] = round(100 - remaining, 2)
            if refresh_match:
                entry["refresh"] = refresh_match.group(1).strip().rstrip("·").strip()
        elif refresh_match and current_limit in result.get(current_group, {}):
            result[current_group][current_limit]["refresh"] = refresh_match.group(1).strip()

    return result


def format_model_quota_section(quota_data: Dict[str, Dict[str, Dict[str, float | str]]]) -> str:
    """Formats parsed quota data for Telegram HTML output."""
    group_labels = {
        "GEMINI MODELS": "Gemini",
        "CLAUDE AND GPT MODELS": "Claude/GPT",
    }
    limit_labels = {
        "five_hour": "Five-Hour",
        "weekly": "Weekly",
    }

    lines = ["📉 <b>Model Quota Usage:</b>"]
    for group, limits in quota_data.items():
        group_label = group_labels.get(group, group.title())
        for limit_key in ("five_hour", "weekly"):
            info = limits.get(limit_key)
            if not info:
                continue
            usage = info["usage"]
            refresh = info.get("refresh")
            line = f"  • {group_label} {limit_labels[limit_key]}: <code>{usage:g}%</code> used"
            if refresh:
                line += f" (resets in {html.escape(str(refresh))})"
            lines.append(line)

    if len(lines) == 1:
        return ""
    return "\n".join(lines) + "\n\n"
