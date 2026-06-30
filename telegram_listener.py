import os
import asyncio
import html
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
            
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            
            stdout_str = stdout.decode('utf-8', errors='replace')
            stderr_str = stderr.decode('utf-8', errors='replace')
            
            if process.returncode != 0:
                error_msg = f"⚠️ Failure in step {step['step_name']}:\n\n"
                if stderr_str.strip():
                    error_msg += f"Stderr:\n{stderr_str[:800]}\n\n"
                if stdout_str.strip():
                    error_msg += f"Stdout:\n{stdout_str[:800]}"
                await update.message.reply_text(error_msg)
                return

            # On success, send a short summary of the output (max 10 lines)
            stdout_lines = [line.strip() for line in stdout_str.splitlines() if line.strip()]
            summary = "\n".join(stdout_lines[-10:]) if stdout_lines else "No console output."
            escaped_summary = html.escape(summary)
            await update.message.reply_text(
                f"✅ Step completed: <b>{step['step_name']}</b>\n\nSummary:\n<pre>{escaped_summary}</pre>",
                parse_mode="HTML"
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
