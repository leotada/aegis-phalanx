import os
import asyncio
import html
import re
import subprocess
import json
from abc import ABC, abstractmethod
from typing import Dict, List, Type
from telegram import Update, BotCommand
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes, Application

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

SESSION_FILE_PATH = "/root/.config/aegis-phalanx/session.json"
AGENT_STEP_TIMEOUT = os.environ.get("AGENT_STEP_TIMEOUT", "5m")
AGENT_INTENT_TIMEOUT = os.environ.get("AGENT_INTENT_TIMEOUT", "15s")

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
    """Classifies user messages using Gemini 3.5 Flash via agy CLI, with keyword fallback."""
    prompt = f"""Classify the user intent for a coding assistant bot.
User message: "{message_text}"

Intents:
- RESUME: The user wants to continue, resume, retry, or finish the last run, or fix the error and try again.
- QUERY_STATUS: The user is asking what was done, what is the status of the last task, or what the agent remembers.
- NEW_DEMAND: The user is requesting a new software engineering task or feature.

Respond with ONLY the classification label (RESUME, QUERY_STATUS, or NEW_DEMAND) in plain text, with no markdown, punctuation, or extra words.
"""
    cmd = [
        "agy",
        "--model", "Gemini 3.5 Flash (Low)",
        "--dangerously-skip-permissions",
        "--print-timeout", AGENT_INTENT_TIMEOUT,
        "--print", prompt
    ]
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        if process.returncode == 0:
            result = stdout.decode('utf-8').strip().upper()
            for label in ["RESUME", "QUERY_STATUS", "NEW_DEMAND"]:
                if label in result:
                    return label
    except Exception:
        pass
    
    # Fallback to simple regex/keyword heuristics if agy call fails
    cleaned = message_text.lower().strip()
    if any(k in cleaned for k in ["continue", "resume", "continuar", "recomecar", "retry", "tentar de novo"]):
        return "RESUME"
    if any(k in cleaned for k in ["status", "memory", "last", "ultima", "o que foi feito", "memoria", "lembra"]):
        return "QUERY_STATUS"
        
    return "NEW_DEMAND"

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
ALLOWED_CHAT_ID = str(TELEGRAM_CHAT_ID) if TELEGRAM_CHAT_ID else None

# ==========================================
# SOLID: Abstractions and Contracts (DIP)
# ==========================================

class AgentCLI(ABC):
    """
    Common abstraction for all AI Agent CLIs (Single Responsibility Principle).
    """
    @abstractmethod
    def build_command(self, prompt: str, model: str, reasoning_budget: str, timeout: str = None) -> List[str]:
        """Generates the terminal argument list to run the tool."""
        pass


# ==========================================
# SOLID: Concrete Implementations (OCP / LSP)
# ==========================================

class AntigravityAgentCLI(AgentCLI):
    """Adapter for the official Antigravity CLI (Google)."""
    def build_command(self, prompt: str, model: str, reasoning_budget: str, timeout: str = None) -> List[str]:
        # Map slugs to the exact names displayed in `agy models`
        model_map = {
            "gemini-3.1-pro": "Gemini 3.1 Pro",
            "gemini-3.5-flash": "Gemini 3.5 Flash"
        }
        
        base_name = model_map.get(model.lower(), model)
        budget = reasoning_budget.capitalize() if reasoning_budget else "Medium"
        full_model_name = f"{base_name} ({budget})"
        effective_timeout = timeout if timeout else AGENT_STEP_TIMEOUT
        
        return [
            "agy",
            "--model", full_model_name,
            "--dangerously-skip-permissions",
            "--print-timeout", effective_timeout,
            "--print", prompt
        ]


class ClaudeCodeAgentCLI(AgentCLI):
    """Adapter for the official Claude Code CLI (Anthropic)."""
    def build_command(self, prompt: str, model: str, reasoning_budget: str, timeout: str = None) -> List[str]:
        return [
            "claude",
            "-p", prompt,
            "-y"  # Non-interactive mode with auto-approval
        ]


class AiderAgentCLI(AgentCLI):
    """Optional adapter for Aider (in case you want to use it in the future)."""
    def build_command(self, prompt: str, model: str, reasoning_budget: str, timeout: str = None) -> List[str]:
        return [
            "aider",
            "--model", model,
            "--message", prompt,
            "--yes",
            "--no-auto-commits"
        ]


# ==========================================
# SOLID: Factory and Modular Registry (OCP / SRP)
# ==========================================

class AgentRegistry:
    """
    Extensible factory for resolving agent instances without direct coupling.
    """
    _registry: Dict[str, Type[AgentCLI]] = {}

    @classmethod
    def register(cls, name: str, cli_class: Type[AgentCLI]) -> None:
        cls._registry[name] = cli_class

    @classmethod
    def get_agent(cls, name: str) -> AgentCLI:
        cli_class = cls._registry.get(name)
        if not cli_class:
            raise ValueError(f"Agent tool '{name}' is not registered.")
        return cli_class()

# Registering adapters in the system
AgentRegistry.register("agy", AntigravityAgentCLI)
AgentRegistry.register("claude", ClaudeCodeAgentCLI)
AgentRegistry.register("aider", AiderAgentCLI)


# ==========================================
# Pipeline Orchestrator (Controller)
# ==========================================

# Declarative and mutable pipeline configuration
PIPELINE_CONFIG = [
    {
        "step_name": "Architect (Planning - PLAN)",
        "tool": "agy",
        "model": "gemini-3.1-pro",
        "reasoning_budget": "high",
        "timeout": "5m",
        "prompt": "Create a new git branch for the feature (switch/create if needed). Read this requirement: '{demand}'. Act as a Software Architect. Write a detailed plan containing all the business context, business rules, and design choices. The plan must contain two separate sections: 1) 'Test Specification Plan' detailing the test cases to be written, expected inputs/outputs, and edge cases for the Test Developer, and 2) 'Implementation Plan' describing the architectural design, file modifications, and guidelines for the Developer. Write this detailed plan to a file named `architect_plan.md` in the root of the repository. Do NOT write any tests or production code yet."
    },
    {
        "step_name": "Test Developer (Testing - RED)",
        "tool": "agy",
        "model": "gemini-3.5-flash",
        "reasoning_budget": "medium",
        "timeout": "10m",
        "prompt": "Read the `architect_plan.md` file created by the Architect in the root of the repository. Act as a Test Developer. Strictly follow the 'Test Specification Plan' section to write and implement all the specified test cases. Run the tests via CLI and prove they fail (TDD RED Phase). Do NOT write any production code. Do NOT delete `architect_plan.md` as it is needed by the Developer in the next step."
    },
    {
        "step_name": "Developer (Implementation - GREEN)",
        "tool": "agy",
        "model": "gemini-3.5-flash",
        "reasoning_budget": "medium",
        "timeout": "10m",
        "prompt": "Read the newly created tests that are currently failing and the `architect_plan.md` file in the root of the repository. Act as a Developer. Strictly follow the 'Implementation Plan' section of `architect_plan.md` to write the minimum and strictly necessary production code to make the tests pass (GREEN Phase). Run the tests until all of them pass perfectly. Run lint and other quality tools to ensure the code quality and fix any issues found. Do NOT delete `architect_plan.md` as it is needed by the Reviewer in the next step."
    },
    {
        "step_name": "Code Reviewer (Review - PLAN)",
        "tool": "agy",
        "model": "gemini-3.5-flash",
        "reasoning_budget": "high",
        "timeout": "10m",
        "prompt": "Act as a Staff Engineer reviewer. Read the `architect_plan.md` file for context and analyze the recent changes. Are all the new important cases being covered with tests? Is the code clean, secure, and free of code smells? Do NOT modify the code or run refactoring. Instead, create a detailed refactoring plan listing all identified issues, code smells, and step-by-step refactoring/fixing instructions. Write this plan into a file named `refactor_plan.md` in the root of the repository. After the review, delete the `architect_plan.md` file."
    },
    {
        "step_name": "Refactoring Developer (Refactoring - REFACTOR)",
        "tool": "agy",
        "model": "gemini-3.5-flash",
        "reasoning_budget": "medium",
        "timeout": "10m",
        "prompt": "Read the `refactor_plan.md` file created by the Code Reviewer in the root of the repository. Strictly follow and execute the plan of the code reviewer to fix and refactor the code. Do not perform any changes that are not in the plan. Ensure that the entire test suite continues to pass after your fixes. Once all fixes and refactoring are successfully done, delete the `refactor_plan.md` file."
    },
    {
        "step_name": "GitOps (Documentation and PR)",
        "tool": "agy",
        "model": "gemini-3.5-flash",
        "reasoning_budget": "low",
        "prompt": "Commit all changes using the Conventional Commits pattern. Push the current branch to origin using `git push origin HEAD`. If the push fails, retry once. Note: The Pull Request will be created automatically by the system orchestrator, so you do NOT need to run `gh pr create` yourself."
    }
]

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
            
    await asyncio.gather(
        read_stream(process.stdout, stdout_chunks, "STDOUT"),
        read_stream(process.stderr, stderr_chunks, "STDERR")
    )
    
    returncode = await process.wait()
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

async def run_pipeline(update: Update, context: ContextTypes.DEFAULT_TYPE, repo_url: str, demand: str, is_resume: bool = False):
    project_dir = "/workspace/project"
    github_token = os.environ.get("GITHUB_TOKEN")

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
        for i, step in enumerate(PIPELINE_CONFIG):
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
            f"⏳ <b>Resuming from step:</b> <code>{PIPELINE_CONFIG[start_index]['step_name']}</code>",
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

    # Check GITHUB_TOKEN requirement (only HTTPS clones require it)
    if not github_token and repo_url and repo_url.startswith("https://github.com/"):
        await update.message.reply_text("❌ Error: GITHUB_TOKEN environment variable is not defined and is required for HTTPS repository cloning.")
        return

    # Authenticate HTTPS repo URL if GITHUB_TOKEN is available
    if github_token and repo_url:
        auth_repo_url = repo_url.replace("https://github.com/", f"https://x-access-token:{github_token}@github.com/")
    else:
        auth_repo_url = repo_url

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
    for idx in range(start_index, len(PIPELINE_CONFIG)):
        step = PIPELINE_CONFIG[idx]
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
                save_session(repo_url, demand, step_name if idx == 0 else PIPELINE_CONFIG[idx-1]["step_name"], steps_status, git_branch)
                
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
            save_session(repo_url, demand, step_name if idx == 0 else PIPELINE_CONFIG[idx-1]["step_name"], steps_status, git_branch)
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

async def handle_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    if chat_id != ALLOWED_CHAT_ID:
        return
    delete_session()
    await update.message.reply_text("🧹 Session memory cleared successfully.")

async def send_status(update: Update):
    session = load_session()
    if not session or "demand" not in session:
        await update.message.reply_text("ℹ️ No active session in memory.")
        return
        
    status_msg = (
        f"🧠 <b>Aegis Session Memory:</b>\n\n"
        f"📦 <b>Repository:</b> <code>{session.get('repo_url', 'N/A')}</code>\n"
        f"💡 <b>Demand:</b> <code>{html.escape(session.get('demand', 'N/A'))}</code>\n"
        f"🌿 <b>Branch:</b> <code>{session.get('git_branch', 'N/A')}</code>\n"
        f"🏁 <b>Last Completed:</b> <code>{session.get('last_completed_step', 'N/A')}</code>\n\n"
        f"📊 <b>Step Statuses:</b>\n"
    )
    for step in PIPELINE_CONFIG:
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
        BotCommand("clear", "Clear active session memory")
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
    app.add_handler(CommandHandler("clear", handle_clear))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_demand))
    return app

if __name__ == '__main__':
    # Verify that required tokens are set in environment
    if not TOKEN or not ALLOWED_CHAT_ID:
        print("Error: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not defined in environment variables.")
        exit(1)
        
    app = build_application()
    app.run_polling()
