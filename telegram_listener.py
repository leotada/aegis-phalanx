import os
import asyncio
import html
import re
import shutil
import subprocess
import json
import select
import struct
import fcntl
import termios
import pty
import time
from typing import Dict, List
from telegram import Update, BotCommand
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes, Application

from agents import AgentRegistry, DEFAULT_AGENT_TOOL, resolve_pipeline_config, resolve_review_pipeline_config
from agents.config import AGENT_INTENT_TIMEOUT, AGENT_STEP_TIMEOUT
from agents.tool_specs import get_tool_spec

def sanitize_environment() -> None:
    """Removes GITHUB_TOKEN if it is set to the default placeholder, empty, or whitespace only."""
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token or token == "your_github_token_here":
        os.environ.pop("GITHUB_TOKEN", None)

sanitize_environment()

def normalize_repo_url(repo: str) -> str:
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


def extract_owner_repo(repo_url: str) -> str | None:
    """
    Extracts the 'owner/repo' slug from any supported GitHub URL format.
    Returns None if the URL cannot be parsed.
    Supported formats:
      - git@github.com:owner/repo.git
      - https://github.com/owner/repo.git
      - https://x-access-token:<token>@github.com/owner/repo.git
    """
    # SSH format: git@github.com:owner/repo or git@github.com:owner/repo.git
    ssh_match = re.match(r'^(?:ssh://)?git@github\.com[:/]([a-zA-Z0-9_\-]+/[a-zA-Z0-9_\-\.]+?)(?:\.git)?$', repo_url.strip(), re.IGNORECASE)
    if ssh_match:
        return ssh_match.group(1)

    # HTTPS format (with optional token auth): https://[token@]github.com/owner/repo[.git]
    https_match = re.match(r'^https?://(?:[^@/]+@)?github\.com/([a-zA-Z0-9_\-]+/[a-zA-Z0-9_\-\.]+?)(?:\.git)?$', repo_url.strip(), re.IGNORECASE)
    if https_match:
        return https_match.group(1)

    return None


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


async def resolve_clone_url(repo_url: str, github_token: str | None) -> tuple[str | None, str, str | None]:
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
    gh_token = await _gh_auth_token()
    if gh_token:
        return _with_token(gh_token), "gh-cli", None

    # 3. SSH key fallback.
    owner_repo = extract_owner_repo(repo_url)
    if owner_repo and await _ssh_github_available():
        return f"git@github.com:{owner_repo}.git", "ssh", None

    return (
        None,
        "none",
        "No GitHub credentials available. Set GITHUB_TOKEN, authenticate the gh CLI "
        "(<code>gh auth login</code>), or configure an SSH key for github.com.",
    )

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
        
        # Clean colons/dashes right after or before the URL
        right_part = re.sub(r'^\s*[:\-]\s*', '', right_part)
        left_part = re.sub(r'\s*[:\-]\s*$', '', left_part)
        
        # Clean prepositions before the URL
        left_part = re.sub(r'\b(in|for|on|to|at|into|from)\s*$', '', left_part, flags=re.IGNORECASE)
        
        clean_demand = (left_part.strip() + " " + right_part.strip()).strip()
        return normalize_repo_url(repo_url), clean_demand

    # 2. Match shorthand owner/repo followed by a colon at the start of the message
    shorthand_colon_match = re.match(
        r'^([a-zA-Z0-9_\-]+/[a-zA-Z0-9_\-\.]+?)(?:\.git)?\s*:\s*(.*)$',
        demand_stripped,
        re.IGNORECASE
    )
    if shorthand_colon_match:
        repo_name = shorthand_colon_match.group(1)
        clean_demand = shorthand_colon_match.group(2).strip()
        return normalize_repo_url(repo_name), clean_demand

    # 3. Match shorthand owner/repo by itself (entire string)
    shorthand_exact_match = re.match(
        r'^([a-zA-Z0-9_\-]+/[a-zA-Z0-9_\-\.]+?)(?:\.git)?$',
        demand_stripped,
        re.IGNORECASE
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

SESSION_FILE_PATH = "/root/.config/aegis-phalanx/session.json"
AGY_SCRATCH_DIR = "/root/.gemini/antigravity-cli/scratch"
AGY_QUOTA_TIMEOUT = int(os.environ.get("AGY_QUOTA_TIMEOUT", "45"))
ACTIVE_TASKS = {}


def save_session(repo_url: str, demand: str, last_completed_step: str, steps_status: dict, git_branch: str, session_file_path: str = SESSION_FILE_PATH) -> None:
    """Saves the current pipeline session metadata to a JSON file."""
    try:
        os.makedirs(os.path.dirname(session_file_path), exist_ok=True)
        data = {
            "repo_url": repo_url,
            "demand": demand,
            "last_completed_step": last_completed_step,
            "steps_status": steps_status,
            "git_branch": git_branch
        }
        with open(session_file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"Error saving session: {e}", flush=True)

def load_session(session_file_path: str = SESSION_FILE_PATH) -> dict:
    """Loads the pipeline session metadata from JSON file. Returns None if it doesn't exist."""
    if not os.path.exists(session_file_path):
        return None
    try:
        with open(session_file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading session: {e}", flush=True)
        return None

def clear_session(session_file_path: str = SESSION_FILE_PATH) -> None:
    """Clears the active task session details but retains the last repo URL."""
    session = load_session(session_file_path)
    if session and "repo_url" in session:
        try:
            data = {"repo_url": session["repo_url"]}
            with open(session_file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            print(f"Error clearing session: {e}", flush=True)
    else:
        if os.path.exists(session_file_path):
            try:
                os.remove(session_file_path)
            except Exception as e:
                print(f"Error clearing session: {e}", flush=True)

def delete_session(session_file_path: str = SESSION_FILE_PATH) -> None:
    """Removes the persistent session file completely (including repo URL)."""
    if os.path.exists(session_file_path):
        try:
            os.remove(session_file_path)
        except Exception as e:
            print(f"Error deleting session file: {e}", flush=True)

async def classify_intent(message_text: str) -> str:
    """Classifies user messages using the active agent CLI, with keyword fallback."""
    prompt = f"""Classify the user intent for a coding assistant bot.
User message: "{message_text}"

Intents:
- RESUME: The user wants to continue, resume, retry, or finish the last run, or fix the error and try again.
- QUERY_STATUS: The user is asking what was done, what is the status of the last task, or what the agent remembers.
- NEW_DEMAND: The user is requesting a new software engineering task or feature.

Respond with ONLY the classification label (RESUME, QUERY_STATUS, or NEW_DEMAND) in plain text, with no markdown, punctuation, or extra words.
"""
    try:
        agent_cli = AgentRegistry.get_agent(DEFAULT_AGENT_TOOL)
        cmd = agent_cli.build_command(
            prompt,
            "gemini-3.5-flash",
            "low",
            timeout=AGENT_INTENT_TIMEOUT,
        )
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode == 0:
            result = stdout.decode('utf-8').strip().upper()
            for label in ["RESUME", "QUERY_STATUS", "NEW_DEMAND"]:
                if label in result:
                    return label
    except Exception:
        pass

    # Fallback to simple regex/keyword heuristics if the agent call fails
    cleaned = message_text.lower().strip()
    if any(k in cleaned for k in ["continue", "resume", "continuar", "recomecar", "retry", "tentar de novo"]):
        return "RESUME"
    if any(k in cleaned for k in ["status", "memory", "last", "ultima", "o que foi feito", "memoria", "lembra"]):
        return "QUERY_STATUS"
        
    return "NEW_DEMAND"

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
ALLOWED_CHAT_ID = str(TELEGRAM_CHAT_ID) if TELEGRAM_CHAT_ID else None

async def run_command_and_stream(command: List[str], cwd: str = "/workspace") -> tuple[int, str, str]:
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd
    )
    
    stdout_chunks = []
    stderr_chunks = []
    
    async def read_stream(stream, chunks, prefix):
        while True:
            line = await stream.readline()
            if not line:
                break
            decoded = line.decode('utf-8', errors='replace')
            chunks.append(decoded)
            print(f"[{prefix}] {decoded.rstrip()}", flush=True)
            
    try:
        await asyncio.gather(
            read_stream(process.stdout, stdout_chunks, "STDOUT"),
            read_stream(process.stderr, stderr_chunks, "STDERR")
        )
        returncode = await process.wait()
    except asyncio.CancelledError:
        try:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
        except ProcessLookupError:
            pass
        raise
    
    return returncode, "".join(stdout_chunks), "".join(stderr_chunks)

def get_git_changes() -> str:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd="/workspace/project",
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
            cwd="/workspace/project",
            capture_output=True,
            text=True,
            check=False
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    return ""

def _strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", text)

def fetch_agy_quota_output(timeout: int = AGY_QUOTA_TIMEOUT) -> str:
    """Runs the agy TUI /usage command via PTY and returns the captured terminal output."""
    os.makedirs(AGY_SCRATCH_DIR, exist_ok=True)
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
        cwd=AGY_SCRATCH_DIR,
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
        plain = _strip_ansi("".join(chunks))

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

    return _strip_ansi("".join(chunks))

def parse_model_quota(text: str) -> Dict[str, Dict[str, Dict[str, float | str]]]:
    """Parses agy /usage output into remaining and usage percentages per model group."""
    result: Dict[str, Dict[str, Dict[str, float | str]]] = {}
    current_group = None
    current_limit = None

    for line in _strip_ansi(text).splitlines():
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

def get_model_quota_summary() -> str:
    """Fetches quota usage when the active tool supports it."""
    if not get_tool_spec(DEFAULT_AGENT_TOOL).supports_quota:
        return ""
    try:
        output = fetch_agy_quota_output()
        quota_data = parse_model_quota(output)
        if not quota_data:
            return ""
        return format_model_quota_section(quota_data)
    except Exception as e:
        print(f"Error fetching model quota: {e}", flush=True)
        return ""

async def run_pipeline(update: Update, context: ContextTypes.DEFAULT_TYPE, repo_url: str, demand: str, is_resume: bool = False):
    chat_id = str(update.effective_chat.id)
    current_task = asyncio.current_task()
    ACTIVE_TASKS[chat_id] = current_task
    
    step_name = None
    idx = None
    try:
        project_dir = "/workspace/project"
        github_token = os.environ.get("GITHUB_TOKEN")
        pipeline_config = resolve_pipeline_config()

        # Setup or load session data
        session_data = load_session()
        steps_status = {}
        git_branch = ""
        
        if is_resume:
            if not session_data:
                await update.message.reply_text("❌ Error: No previous session found to resume.")
                return
            repo_url = session_data["repo_url"]
            demand = session_data["demand"]
            git_branch = session_data["git_branch"]
            steps_status = session_data.get("steps_status", {})
            
            # Determine starting step index
            start_index = 0
            for i, step in enumerate(pipeline_config):
                step_name = step["step_name"]
                if steps_status.get(step_name) != "success":
                    start_index = i
                    break
            else:
                await update.message.reply_text("✅ All steps in the last pipeline were already completed successfully!")
                return
                
            await update.message.reply_text(
                f"🔄 <b>Resuming pipeline for:</b>\n"
                f"📦 <b>Repository:</b> <code>{repo_url}</code>\n"
                f"💡 <b>Demand:</b> <code>{html.escape(demand)}</code>\n"
                f"⏳ <b>Resuming from step:</b> <code>{pipeline_config[start_index]['step_name']}</code>",
                parse_mode="HTML"
            )
        else:
            # New demand: clean up previous session if any
            clear_session()
            start_index = 0
            # Determine git branch name based on demand description
            clean_name = re.sub(r'[^a-zA-Z0-9]', '-', demand.lower())[:30].strip('-')
            git_branch = f"feature/{clean_name}"
            
            await update.message.reply_text(
                f"🚀 <b>Starting Multi-Model TDD Pipeline</b>\n"
                f"📦 <b>Repository:</b> <code>{repo_url}</code>\n"
                f"💡 <b>Demand:</b> <code>{html.escape(demand)}</code>",
                parse_mode="HTML"
            )

        # Resolve credentials for cloning: GITHUB_TOKEN -> gh CLI -> SSH key
        auth_repo_url, auth_method, auth_error = await resolve_clone_url(repo_url, github_token)
        if auth_error:
            await update.message.reply_text(f"❌ Error: {auth_error}", parse_mode="HTML")
            return

        # Repository setup
        try:
            # If it is a new run, or the project folder is missing, we clone
            if not is_resume or not os.path.exists(project_dir):
                if os.path.exists(project_dir):
                    proc = await asyncio.create_subprocess_exec("rm", "-rf", project_dir)
                    await proc.wait()

                await update.message.reply_text("📥 Cloning repository...")
                clone_proc = await asyncio.create_subprocess_exec(
                    "git", "clone", auth_repo_url, project_dir,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout_c, stderr_c = await clone_proc.communicate()
                
                if clone_proc.returncode != 0:
                    err = stderr_c.decode('utf-8', errors='replace')[:800]
                    await update.message.reply_text(
                        f"❌ <b>Failed to clone repository.</b>\n<b>Stderr:</b>\n<pre>{html.escape(err)}</pre>",
                        parse_mode="HTML"
                    )
                    return

                for key, val in [("user.name", "Aegis Agent"), ("user.email", "agent@aegis-phalanx.local")]:
                    proc = await asyncio.create_subprocess_exec("git", "config", key, val, cwd=project_dir)
                    await proc.wait()

            # Handle branch checkout for resume or new demand
            if is_resume:
                # Check if the branch exists locally
                branch_exists_local = False
                proc = await asyncio.create_subprocess_exec(
                    "git", "show-ref", "--verify", f"refs/heads/{git_branch}",
                    cwd=project_dir
                )
                await proc.wait()
                if proc.returncode == 0:
                    branch_exists_local = True

                if branch_exists_local:
                    proc = await asyncio.create_subprocess_exec("git", "checkout", git_branch, cwd=project_dir)
                    await proc.wait()
                else:
                    # Try checkout from origin
                    proc = await asyncio.create_subprocess_exec(
                        "git", "checkout", "-b", git_branch, f"origin/{git_branch}",
                        cwd=project_dir
                    )
                    await proc.wait()
                    if proc.returncode != 0:
                        await update.message.reply_text(
                            f"⚠️ <b>Warning:</b> The local branch <code>{git_branch}</code> and its commits were lost because the container was rebuilt or the directory was cleaned.\n"
                            "Cannot resume. Restarting the pipeline from the beginning...",
                            parse_mode="HTML"
                        )
                        start_index = 0
                        is_resume = False
                        # Create new branch
                        proc = await asyncio.create_subprocess_exec("git", "checkout", "-b", git_branch, cwd=project_dir)
                        await proc.wait()
            else:
                # Create new branch
                proc = await asyncio.create_subprocess_exec("git", "checkout", "-b", git_branch, cwd=project_dir)
                await proc.wait()

        except Exception as e:
            await update.message.reply_text(f"❌ Initialization error: {str(e)}")
            return

        # Execute step loop
        for idx in range(start_index, len(pipeline_config)):
            step = pipeline_config[idx]
            step_name = step["step_name"]
            
            await update.message.reply_text(
                f"⏳ <b>Executing:</b> {step_name}\n🔧 <b>CLI:</b> <code>{step['tool']}</code> | <b>Model:</b> <code>{step['model']}</code> (Thinking: {step['reasoning_budget']})",
                parse_mode="HTML"
            )
            
            prompt_content = step['prompt'].format(
                demand=demand,
                repo_owner_name=extract_owner_repo(repo_url) or repo_url
            )
            
            try:
                agent_cli = AgentRegistry.get_agent(step['tool'])
                command = agent_cli.build_command(
                    prompt=prompt_content,
                    model=step['model'],
                    reasoning_budget=step['reasoning_budget'],
                    timeout=step.get('timeout')
                )
                
                returncode, stdout_str, stderr_str = await run_command_and_stream(command, cwd=project_dir)
                
                if returncode != 0:
                    # Mark step as failed
                    steps_status[step_name] = "failed"
                    save_session(repo_url, demand, step_name if idx == 0 else pipeline_config[idx-1]["step_name"], steps_status, git_branch)
                    
                    error_msg = f"⚠️ <b>Failure in step {step_name}:</b>\n\n"
                    if stderr_str.strip():
                        error_msg += f"<b>Stderr:</b>\n<pre>{html.escape(stderr_str[:800])}</pre>\n\n"
                    if stdout_str.strip():
                        error_msg += f"<b>Stdout:</b>\n<pre>{html.escape(stdout_str[:800])}</pre>"
                    await update.message.reply_text(error_msg, parse_mode="HTML")
                    return

                # Mark step as successful
                steps_status[step_name] = "success"
                save_session(repo_url, demand, step_name, steps_status, git_branch)

                # Generate smart summary of key metrics
                pytest_sum = get_pytest_summary(stdout_str)
                git_changes = get_git_changes()
                pr_url = get_pr_url()
                
                summary_parts = []
                summary_parts.append(f"✅ <b>{step_name} completed successfully!</b>")
                
                if git_changes:
                    summary_parts.append(f"<b>Files changed:</b>\n{git_changes}")
                    
                if pytest_sum:
                    summary_parts.append(f"<b>Tests status:</b> <code>{pytest_sum}</code>")
                    
                if pr_url:
                    summary_parts.append(f"<b>PR Created:</b> <a href=\"{pr_url}\">{pr_url}</a>")
                    
                # Fallback if no specific info was parsed
                if not pytest_sum and not git_changes and not pr_url:
                    stdout_lines = [line.strip() for line in stdout_str.splitlines() if line.strip()]
                    last_lines = "\n".join(stdout_lines[-7:]) if stdout_lines else "No console output."
                    last_lines_escaped = html.escape(last_lines)
                    last_lines_formatted = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', last_lines_escaped)
                    summary_parts.append(f"<b>Output Tail:</b>\n{last_lines_formatted}")
                    
                await update.message.reply_text(
                    "\n\n".join(summary_parts),
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )
                    
            except Exception as e:
                steps_status[step_name] = "failed"
                save_session(repo_url, demand, step_name if idx == 0 else pipeline_config[idx-1]["step_name"], steps_status, git_branch)
                await update.message.reply_text(f"❌ System error in step {step_name}: {str(e)}")
                return

        final_pr_url = get_pr_url()
        if not final_pr_url:
            repo_owner_name = extract_owner_repo(repo_url) or repo_url
            await update.message.reply_text("⏳ <b>Creating Pull Request...</b>", parse_mode="HTML")
            try:
                proc = await asyncio.create_subprocess_exec(
                    "gh", "pr", "create", "--fill", "--repo", repo_owner_name,
                    cwd=project_dir,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout_pr, stderr_pr = await proc.communicate()
                if proc.returncode == 0:
                    final_pr_url = get_pr_url()
                else:
                    err_msg = stderr_pr.decode('utf-8', errors='replace').strip()
                    await update.message.reply_text(f"⚠️ <b>Failed to create PR via CLI:</b>\n<pre>{html.escape(err_msg[:800])}</pre>", parse_mode="HTML")
            except Exception as e:
                await update.message.reply_text(f"⚠️ <b>Error creating PR:</b> <code>{html.escape(str(e))}</code>", parse_mode="HTML")

        if final_pr_url:
            await update.message.reply_text(
                f"✅ <b>Multi-Model Pipeline completed successfully!</b>\n\n🔗 <b>PR Opened:</b> <a href=\"{final_pr_url}\">{final_pr_url}</a>",
                parse_mode="HTML",
                disable_web_page_preview=True
            )
        else:
            await update.message.reply_text(
                "✅ <b>Multi-Model Pipeline completed!</b>\n\n"
                "⚠️ Could not confirm PR URL — check the repository manually or use <code>/status</code> to review completed steps.",
                parse_mode="HTML"
            )
        clear_session()
    except asyncio.CancelledError:
        if step_name:
            steps_status[step_name] = "failed"
            last_completed = step_name if (idx is not None and idx == 0) else pipeline_config[idx-1]["step_name"]
            save_session(repo_url, demand, last_completed, steps_status, git_branch)
            await update.message.reply_text(
                f"🛑 <b>Pipeline stopped in step:</b> <code>{step_name}</code>\n"
                "You can resume later with <code>/continue</code>.",
                parse_mode="HTML"
            )
        else:
            await update.message.reply_text("🛑 Pipeline stopped during initialization.")
        raise
    finally:
        if ACTIVE_TASKS.get(chat_id) == current_task:
            ACTIVE_TASKS.pop(chat_id, None)

async def fetch_pr_context(
    repo_owner_name: str,
    pr_number: int,
    project_dir: str,
    max_diff_chars: int = 120_000,
) -> str:
    """Fetches PR metadata and diff via gh for injection into the review prompt."""
    sections: list[str] = []

    view_proc = await asyncio.create_subprocess_exec(
        "gh", "pr", "view", str(pr_number), "--repo", repo_owner_name,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    view_out, view_err = await view_proc.communicate()
    if view_proc.returncode == 0:
        sections.append(view_out.decode("utf-8", errors="replace").strip())
    else:
        err = view_err.decode("utf-8", errors="replace").strip()
        sections.append(f"(Could not fetch PR metadata: {err[:500]})")

    diff_proc = await asyncio.create_subprocess_exec(
        "gh", "pr", "diff", str(pr_number), "--repo", repo_owner_name,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=project_dir,
    )
    diff_out, diff_err = await diff_proc.communicate()
    if diff_proc.returncode == 0:
        diff_text = diff_out.decode("utf-8", errors="replace").strip()
        if len(diff_text) > max_diff_chars:
            diff_text = diff_text[:max_diff_chars] + "\n\n… (diff truncated)"
        sections.append("--- Diff ---\n" + diff_text)
    else:
        err = diff_err.decode("utf-8", errors="replace").strip()
        sections.append(f"(Could not fetch PR diff: {err[:500]})")

    return "\n\n".join(sections)

async def run_pr_review(update: Update, context: ContextTypes.DEFAULT_TYPE, repo_url: str, pr_number: int):
    """Clones a repo, runs a single PR review step, and returns only the review text."""
    project_dir = "/workspace/project"
    repo_owner_name = extract_owner_repo(repo_url) or repo_url
    github_token = os.environ.get("GITHUB_TOKEN")
    review_config = resolve_review_pipeline_config()
    step = review_config[0]

    # Resolve credentials for cloning: GITHUB_TOKEN -> gh CLI -> SSH key
    auth_repo_url, auth_method, auth_error = await resolve_clone_url(repo_url, github_token)
    if auth_error:
        await update.message.reply_text(f"❌ Error: {auth_error}", parse_mode="HTML")
        return

    try:
        if os.path.exists(project_dir):
            proc = await asyncio.create_subprocess_exec("rm", "-rf", project_dir)
            await proc.wait()

        clone_proc = await asyncio.create_subprocess_exec(
            "git", "clone", auth_repo_url, project_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr_c = await clone_proc.communicate()
        if clone_proc.returncode != 0:
            err = stderr_c.decode("utf-8", errors="replace")[:800]
            await update.message.reply_text(
                f"❌ <b>Failed to clone repository.</b>\n<b>Stderr:</b>\n<pre>{html.escape(err)}</pre>",
                parse_mode="HTML",
            )
            return

        checkout_proc = await asyncio.create_subprocess_exec(
            "gh", "pr", "checkout", str(pr_number), "--repo", repo_owner_name,
            cwd=project_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, checkout_err = await checkout_proc.communicate()
        if checkout_proc.returncode != 0:
            err = checkout_err.decode("utf-8", errors="replace")[:800]
            await update.message.reply_text(
                f"❌ <b>Failed to checkout PR #{pr_number}.</b>\n<b>Stderr:</b>\n<pre>{html.escape(err)}</pre>",
                parse_mode="HTML",
            )
            return

        prompt_content = step["prompt"].format(
            pr_number=pr_number,
            repo_owner_name=repo_owner_name,
            pr_context=await fetch_pr_context(repo_owner_name, pr_number, project_dir),
        )

        agent_cli = AgentRegistry.get_agent(step["tool"])
        command = agent_cli.build_command(
            prompt=prompt_content,
            model=step["model"],
            reasoning_budget=step["reasoning_budget"],
            timeout=step.get("timeout"),
            read_only=True,
        )

        returncode, stdout_str, stderr_str = await run_command_and_stream(command, cwd=project_dir)

        if returncode != 0:
            error_msg = f"❌ <b>PR review failed.</b>\n\n"
            if stderr_str.strip():
                error_msg += f"<b>Stderr:</b>\n<pre>{html.escape(stderr_str[:800])}</pre>\n\n"
            if stdout_str.strip():
                error_msg += f"<b>Stdout:</b>\n<pre>{html.escape(stdout_str[:800])}</pre>"
            await update.message.reply_text(error_msg, parse_mode="HTML")
            return

        review_text = stdout_str.strip()
        if not review_text:
            await update.message.reply_text("❌ PR review returned no output.")
            return

        await _send_review_text(update, review_text)

    except Exception as e:
        await update.message.reply_text(f"❌ PR review error: {html.escape(str(e))}", parse_mode="HTML")

def _inline_markdown_to_html(text: str) -> str:
    """Converts inline Markdown (bold, italic, code, links, headings) to Telegram HTML."""
    # Protect inline code spans from further processing / escaping.
    inline_code: list[str] = []

    def _stash_inline_code(match: "re.Match[str]") -> str:
        inline_code.append(f"<code>{html.escape(match.group(1))}</code>")
        return f"\x00IC{len(inline_code) - 1}\x00"

    text = re.sub(r"`([^`\n]+)`", _stash_inline_code, text)

    # Escape everything else so raw HTML in the model output can't break parsing.
    text = html.escape(text)

    # Links: [label](https://url) — the URL is already HTML-escaped by the step above.
    text = re.sub(
        r"\[([^\]]+)\]\((https?://[^\s)]+)\)",
        lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>',
        text,
    )

    # Bold: **text** or __text__
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text, flags=re.DOTALL)
    text = re.sub(r"(?<!_)__(.+?)__(?!_)", r"<b>\1</b>", text, flags=re.DOTALL)

    # Strikethrough: ~~text~~
    text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text, flags=re.DOTALL)

    # Italic: *text* / _text_ (single markers, not bullet lists or bold leftovers)
    text = re.sub(r"(?<![\*\w])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\*\w])", r"<i>\1</i>", text)
    text = re.sub(r"(?<![_\w])_(?!\s)([^_\n]+?)(?<!\s)_(?![_\w])", r"<i>\1</i>", text)

    # Headings (# .. ######) become bold lines.
    text = re.sub(r"(?m)^\s*#{1,6}\s+(.+?)\s*$", r"<b>\1</b>", text)

    # Restore inline code spans.
    text = re.sub(r"\x00IC(\d+)\x00", lambda m: inline_code[int(m.group(1))], text)
    return text


def _split_markdown_blocks(text: str) -> list[tuple[str, str, str]]:
    """Splits Markdown into ordered (kind, language, content) blocks.

    kind is either "code" (fenced block) or "text". language is only set for code.
    """
    blocks: list[tuple[str, str, str]] = []
    fence_re = re.compile(r"```([^\n`]*)\n?(.*?)```", re.DOTALL)
    pos = 0
    for match in fence_re.finditer(text):
        if match.start() > pos:
            blocks.append(("text", "", text[pos:match.start()]))
        lang = match.group(1).strip()
        code = match.group(2)
        if code.endswith("\n"):
            code = code[:-1]
        blocks.append(("code", lang, code))
        pos = match.end()
    if pos < len(text):
        blocks.append(("text", "", text[pos:]))
    return blocks


def render_markdown_messages(text: str, max_len: int = 3800) -> list[str]:
    """Renders Markdown into Telegram-HTML message chunks with code syntax highlighting.

    Fenced code blocks become <pre><code class="language-..."> so Telegram applies
    syntax highlighting. Each returned chunk is self-contained, well-formed HTML that
    fits within max_len, and code blocks are never split across a tag boundary.
    """
    messages: list[str] = []
    buffer = ""

    def flush() -> None:
        nonlocal buffer
        if buffer:
            messages.append(buffer)
            buffer = ""

    def push(segment: str) -> None:
        nonlocal buffer
        if not segment:
            return
        if not buffer:
            buffer = segment
        elif len(buffer) + 1 + len(segment) <= max_len:
            buffer = f"{buffer}\n{segment}"
        else:
            flush()
            buffer = segment

    for kind, lang, content in _split_markdown_blocks(text):
        if kind == "code":
            opener = f'<pre><code class="language-{html.escape(lang)}">' if lang else "<pre>"
            closer = "</code></pre>" if lang else "</pre>"
            escaped = html.escape(content)
            if len(opener) + len(escaped) + len(closer) <= max_len:
                push(f"{opener}{escaped}{closer}")
                continue
            # Code block too large: split by lines, re-wrapping each chunk.
            flush()
            budget = max(1, max_len - len(opener) - len(closer))
            current = ""
            for line in escaped.split("\n"):
                while len(line) > budget:
                    if current:
                        messages.append(f"{opener}{current}{closer}")
                        current = ""
                    messages.append(f"{opener}{line[:budget]}{closer}")
                    line = line[budget:]
                if current and len(current) + 1 + len(line) > budget:
                    messages.append(f"{opener}{current}{closer}")
                    current = ""
                current = f"{current}\n{line}" if current else line
            if current:
                push(f"{opener}{current}{closer}")
        else:
            html_text = _inline_markdown_to_html(content)
            if len(html_text) <= max_len:
                push(html_text)
                continue
            # Text block too large: split on line boundaries to keep inline tags intact.
            flush()
            current = ""
            for line in html_text.split("\n"):
                if len(line) > max_len:
                    if current:
                        messages.append(current)
                        current = ""
                    for i in range(0, len(line), max_len):
                        messages.append(line[i:i + max_len])
                    continue
                if current and len(current) + 1 + len(line) > max_len:
                    messages.append(current)
                    current = ""
                current = f"{current}\n{line}" if current else line
            if current:
                push(current)

    flush()
    return messages


async def _send_review_text(update: Update, review_text: str) -> None:
    """Sends the review text to Telegram as formatted Markdown, splitting into chunks if needed."""
    for chunk in render_markdown_messages(review_text):
        await update.message.reply_text(
            chunk, parse_mode="HTML", disable_web_page_preview=True
        )

async def handle_demand(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    if chat_id != ALLOWED_CHAT_ID:
        return

    raw_demand = update.message.text
    
    # Classify intent using Gemini CLI or keyword fallbacks
    intent = await classify_intent(raw_demand)
    
    if intent == "RESUME":
        await run_pipeline(update, context, None, None, is_resume=True)
    elif intent == "QUERY_STATUS":
        await send_status(update)
    else:
        # NEW_DEMAND
        default_repo = os.environ.get("DEFAULT_REPO")
        session = load_session()
        last_repo = session.get("repo_url") if session else None
        repo_url, demand = parse_demand(raw_demand, default_repo, last_repo)
        
        if not repo_url:
            await update.message.reply_text(
                "❌ Error: No repository specified. Please prefix your demand with your repository (e.g. `owner/repo: my demand`) or configure `DEFAULT_REPO` in .env."
            )
            return
            
        await run_pipeline(update, context, repo_url, demand, is_resume=False)

async def handle_continue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    if chat_id != ALLOWED_CHAT_ID:
        return
    await run_pipeline(update, context, None, None, is_resume=True)

async def handle_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    if chat_id != ALLOWED_CHAT_ID:
        return
    await send_status(update)

async def handle_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    if chat_id != ALLOWED_CHAT_ID:
        return
    task = ACTIVE_TASKS.get(chat_id)
    if task and not task.done():
        task.cancel()
        await update.message.reply_text("🛑 Request to stop the pipeline sent.")
    else:
        await update.message.reply_text("ℹ️ No running pipeline to stop.")

async def handle_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    if chat_id != ALLOWED_CHAT_ID:
        return
    delete_session()
    await update.message.reply_text("🧹 Session memory cleared successfully.")

async def handle_review(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    if chat_id != ALLOWED_CHAT_ID:
        return

    default_repo = os.environ.get("DEFAULT_REPO")
    repo_url, pr_number = parse_pr_reference(update.message.text or "", default_repo)

    if not repo_url or pr_number is None:
        await update.message.reply_text(
            "❌ Usage: <code>/review owner/repo#123</code>\n"
            "Formats: <code>owner/repo#123</code>, <code>owner/repo:123</code>, "
            "<code>https://github.com/owner/repo/pull/123</code>, or <code>/review 123</code> with DEFAULT_REPO set.",
            parse_mode="HTML",
        )
        return

    await run_pr_review(update, context, repo_url, pr_number)

async def send_status(update: Update):
    session = load_session()
    if not session:
        await update.message.reply_text("ℹ️ No active session in memory.")
        return
        
    if "demand" not in session:
        repo_url = session.get("repo_url")
        quota_section = await asyncio.to_thread(get_model_quota_summary)
        if repo_url:
            status_msg = (
                f"ℹ️ No active session in memory.\n"
                f"📦 <b>Remembered Repository:</b> <code>{repo_url}</code>"
            )
            if quota_section:
                status_msg += f"\n\n{quota_section.rstrip()}"
            await update.message.reply_text(status_msg, parse_mode="HTML")
        else:
            if quota_section:
                await update.message.reply_text(quota_section.rstrip(), parse_mode="HTML")
            else:
                await update.message.reply_text("ℹ️ No active session in memory.")
        return

    quota_section = await asyncio.to_thread(get_model_quota_summary)
        
    status_msg = (
        f"🧠 <b>Aegis Session Memory:</b>\n\n"
        f"📦 <b>Repository:</b> <code>{session.get('repo_url', 'N/A')}</code>\n"
        f"💡 <b>Demand:</b> <code>{html.escape(session.get('demand', 'N/A'))}</code>\n"
        f"🌿 <b>Branch:</b> <code>{session.get('git_branch', 'N/A')}</code>\n"
        f"🏁 <b>Last Completed:</b> <code>{session.get('last_completed_step', 'N/A')}</code>\n\n"
    )
    if quota_section:
        status_msg += quota_section
    status_msg += "📊 <b>Step Statuses:</b>\n"
    pipeline_config = resolve_pipeline_config()
    for step in pipeline_config:
        step_name = step["step_name"]
        status = session.get("steps_status", {}).get(step_name, "pending")
        icon = "✅" if status == "success" else "❌" if status == "failed" else "⏳"
        status_msg += f"{icon} {step_name}: <code>{status}</code>\n"
        
    await update.message.reply_text(status_msg, parse_mode="HTML")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) == ALLOWED_CHAT_ID:
        await update.message.reply_text("🤖 Multi-Agent System Online. Awaiting requirements...")

async def post_init(application: Application) -> None:
    """Registers slash commands in the Telegram client UI."""
    await application.bot.set_my_commands([
        BotCommand("start", "Start the bot and get instructions"),
        BotCommand("continue", "Resume the last paused/failed pipeline step"),
        BotCommand("status", "Query current pipeline status and memory"),
        BotCommand("stop", "Stop the current running pipeline"),
        BotCommand("clear", "Clear active session memory"),
        BotCommand("review", "Review an existing GitHub PR"),
    ])

def build_application() -> Application:
    """Builds and returns the Application instance with registered handlers and post_init."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN is not defined in environment variables.")
        
    app = ApplicationBuilder().token(token).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("continue", handle_continue))
    app.add_handler(CommandHandler("status", handle_status))
    app.add_handler(CommandHandler("stop", handle_stop))
    app.add_handler(CommandHandler("clear", handle_clear))
    app.add_handler(CommandHandler("review", handle_review))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_demand))
    return app

if __name__ == '__main__':  # pragma: no cover
    # Verify that required tokens are set in environment
    if not TOKEN or not ALLOWED_CHAT_ID:
        print("Error: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not defined in environment variables.")
        exit(1)
        
    app = build_application()
    app.run_polling()
