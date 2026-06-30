import os
import asyncio
import html
import re
import subprocess
from abc import ABC, abstractmethod
from typing import Dict, List, Type
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
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
    def build_command(self, prompt: str, model: str, reasoning_budget: str) -> List[str]:
        """Generates the terminal argument list to run the tool."""
        pass


# ==========================================
# SOLID: Concrete Implementations (OCP / LSP)
# ==========================================

class AntigravityAgentCLI(AgentCLI):
    """Adapter for the official Antigravity CLI (Google)."""
    def build_command(self, prompt: str, model: str, reasoning_budget: str) -> List[str]:
        # Map slugs to the exact names displayed in `agy models`
        model_map = {
            "gemini-3.1-pro": "Gemini 3.1 Pro",
            "gemini-3.5-flash": "Gemini 3.5 Flash"
        }
        
        base_name = model_map.get(model.lower(), model)
        budget = reasoning_budget.capitalize() if reasoning_budget else "Medium"
        full_model_name = f"{base_name} ({budget})"
        
        return [
            "agy",
            "--model", full_model_name,
            "--dangerously-skip-permissions",
            "--print", prompt
        ]


class ClaudeCodeAgentCLI(AgentCLI):
    """Adapter for the official Claude Code CLI (Anthropic)."""
    def build_command(self, prompt: str, model: str, reasoning_budget: str) -> List[str]:
        return [
            "claude",
            "-p", prompt,
            "-y"  # Non-interactive mode with auto-approval
        ]


class AiderAgentCLI(AgentCLI):
    """Optional adapter for Aider (in case you want to use it in the future)."""
    def build_command(self, prompt: str, model: str, reasoning_budget: str) -> List[str]:
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
        "step_name": "Architect (Planning and Testing - RED)",
        "tool": "agy",
        "model": "gemini-3.1-pro",
        "reasoning_budget": "high",
        "prompt": "Create a new git branch for the feature. Read this requirement: '{demand}'. Act as a Software Architect. Create ONLY the test suite (TDD RED Phase) for this feature. Run the tests via CLI and prove they fail. Do NOT write any production code yet."
    },
    {
        "step_name": "Developer (Implementation - GREEN)",
        "tool": "agy",
        "model": "gemini-3.5-flash",
        "reasoning_budget": "medium",
        "prompt": "Read the newly created tests that are currently failing. Write the minimum and strictly necessary production code to make the tests pass (GREEN Phase). Run the tests until all of them pass perfectly."
    },
    {
        "step_name": "Code Reviewer (Refactoring - REFACTOR)",
        "tool": "agy",
        "model": "gemini-3.5-flash",
        "reasoning_budget": "high",
        "prompt": "Act as a Staff Engineer reviewer. Analyze the recent changes. Was the TDD principle respected? Is the code clean, secure, and free of code smells? If not, refactor the code while ensuring the test suite continues to pass."
    },
    {
        "step_name": "GitOps (Documentation and PR)",
        "tool": "agy",
        "model": "gemini-3.5-flash",
        "reasoning_budget": "low",
        "prompt": "Commit all changes using the Conventional Commits pattern. Push the current branch to origin. Use the 'gh' (GitHub CLI) tool to open a Pull Request detailing what was implemented and the test coverage."
    }
]

async def run_command_and_stream(command: List[str]) -> tuple[int, str, str]:
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
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
            cwd="/workspace",
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

def get_pr_url(output: str) -> str:
    match = re.search(r'(https://github\.com/[^\s]+/pull/\d+)', output)
    if match:
        return match.group(1)
    return ""

async def handle_demand(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    if chat_id != ALLOWED_CHAT_ID:
        return

    demand = update.message.text
    await update.message.reply_text(f"🚀 Starting Multi-Model TDD Pipeline for demand:\n\n{demand}")

    for step in PIPELINE_CONFIG:
        await update.message.reply_text(
            f"⏳ Executing: {step['step_name']}\n🔧 CLI: `{step['tool']}` | Model: `{step['model']}` (Thinking: {step['reasoning_budget']})"
        )
        
        prompt_content = step['prompt'].format(demand=demand)
        
        try:
            # Get the abstracted concrete implementation (DIP / OCP)
            agent_cli = AgentRegistry.get_agent(step['tool'])
            command = agent_cli.build_command(
                prompt=prompt_content,
                model=step['model'],
                reasoning_budget=step['reasoning_budget']
            )
            
            returncode, stdout_str, stderr_str = await run_command_and_stream(command)
            
            if returncode != 0:
                error_msg = f"⚠️ Failure in step {step['step_name']}:\n\n"
                if stderr_str.strip():
                    error_msg += f"Stderr:\n{stderr_str[:800]}\n\n"
                if stdout_str.strip():
                    error_msg += f"Stdout:\n{stdout_str[:800]}"
                await update.message.reply_text(error_msg)
                return

            # Generate smart summary of key metrics
            pytest_sum = get_pytest_summary(stdout_str)
            git_changes = get_git_changes()
            pr_url = get_pr_url(stdout_str)
            
            summary_parts = []
            summary_parts.append(f"✅ <b>{step['step_name']} completed successfully!</b>")
            
            if git_changes:
                summary_parts.append(f"<b>Files changed:</b>\n{git_changes}")
                
            if pytest_sum:
                summary_parts.append(f"<b>Tests status:</b> <code>{pytest_sum}</code>")
                
            if pr_url:
                summary_parts.append(f"<b>PR Created:</b> <a href=\"{pr_url}\">{pr_url}</a>")
                
            # Fallback if no specific info was parsed
            if not pytest_sum and not git_changes and not pr_url:
                stdout_lines = [line.strip() for line in stdout_str.splitlines() if line.strip()]
                last_lines = "\n".join(stdout_lines[-5:]) if stdout_lines else "No console output."
                summary_parts.append(f"<b>Output Tail:</b>\n<pre>{html.escape(last_lines)}</pre>")
                
            await update.message.reply_text(
                "\n\n".join(summary_parts),
                parse_mode="HTML",
                disable_web_page_preview=True
            )
                
        except Exception as e:
            await update.message.reply_text(f"❌ System error in step {step['step_name']}: {str(e)}")
            return

    await update.message.reply_text("✅ Multi-Model Pipeline completed successfully! PR opened on repository.")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) == ALLOWED_CHAT_ID:
        await update.message.reply_text("🤖 Multi-Agent System Online. Awaiting requirements...")

if __name__ == '__main__':
    # Verify that required tokens are set in environment
    if not TOKEN or not ALLOWED_CHAT_ID:
        print("Error: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not defined in environment variables.")
        exit(1)
        
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_demand))
    app.run_polling()
