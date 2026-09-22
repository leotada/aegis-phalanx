"""Telegram command controller. Dependencies are looked up on the composition-root host."""

from __future__ import annotations

import asyncio
import html
import os

from telegram import Update, BotCommand
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    Application,
)


class BotController:
    """Handles Telegram commands and free-form demands for one bot process."""

    def __init__(self, host):
        self.host = host

    def _chat_allowed(self, update: Update) -> bool:
        return str(update.effective_chat.id) == self.host.ALLOWED_CHAT_ID

    def _pipeline_active(self, chat_id: str) -> bool:
        task = self.host.ACTIVE_TASKS.get(chat_id)
        return task is not None and not task.done()

    async def _reject_if_pipeline_active(self, update: Update) -> bool:
        """Returns True when a pipeline is already running and the request was rejected."""
        chat_id = str(update.effective_chat.id)
        if self._pipeline_active(chat_id):
            await update.message.reply_text(self.host.PIPELINE_BUSY_MSG, parse_mode="HTML")
            return True
        return False

    async def handle_demand(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._chat_allowed(update):
            return

        raw_demand = update.message.text

        # Classify intent using Gemini CLI or keyword fallbacks
        intent = await self.host.classify_intent(raw_demand)

        if intent == "RESUME":
            if await self._reject_if_pipeline_active(update):
                return
            await self.host.run_pipeline(update, context, None, None, is_resume=True)
        elif intent == "QUERY_STATUS":
            await self.host.send_status(update)
        else:
            # NEW_DEMAND
            default_repo = os.environ.get("DEFAULT_REPO")
            session = self.host.load_session()
            last_repo = session.get("repo_url") if session else None
            clean_raw, mode = self.host.extract_pipeline_mode(raw_demand)
            repo_url, demand = self.host.parse_demand(clean_raw, default_repo, last_repo)

            # Also check demand itself in case format was repo: [hard] demand
            demand, demand_mode = self.host.extract_pipeline_mode(demand)
            if mode == self.host.MODE_EASY and demand_mode == self.host.MODE_HARD:
                mode = self.host.MODE_HARD

            if not repo_url:
                await update.message.reply_text(
                    "❌ Error: No repository specified. Please prefix your demand with your repository (e.g. `owner/repo: my demand`) or configure `DEFAULT_REPO` in .env."
                )
                return

            if await self._reject_if_pipeline_active(update):
                return

            await self.host.run_pipeline(update, context, repo_url, demand, mode=mode, is_resume=False)

    async def handle_continue(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._chat_allowed(update):
            return
        if await self._reject_if_pipeline_active(update):
            return
        await self.host.run_pipeline(update, context, None, None, is_resume=True)

    async def handle_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._chat_allowed(update):
            return
        await self.host.send_status(update)

    async def handle_stop(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._chat_allowed(update):
            return
        chat_id = str(update.effective_chat.id)
        task = self.host.ACTIVE_TASKS.get(chat_id)
        if task and not task.done():
            task.cancel()
            await update.message.reply_text("🛑 Request to stop the pipeline sent.")
        else:
            await update.message.reply_text("ℹ️ No running pipeline to stop.")

    async def handle_clear(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._chat_allowed(update):
            return
        self.host.delete_session()
        await update.message.reply_text("🧹 Session memory cleared successfully.")

    async def handle_review(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._chat_allowed(update):
            return

        default_repo = os.environ.get("DEFAULT_REPO")
        repo_url, pr_number = self.host.parse_pr_reference(update.message.text or "", default_repo)

        if not repo_url or pr_number is None:
            await update.message.reply_text(
                "❌ Usage: <code>/review owner/repo#123</code>\n"
                "Formats: <code>owner/repo#123</code>, <code>owner/repo:123</code>, "
                "<code>https://github.com/owner/repo/pull/123</code>, or <code>/review 123</code> with DEFAULT_REPO set.",
                parse_mode="HTML",
            )
            return

        if await self._reject_if_pipeline_active(update):
            return

        await self.host.run_pr_review(update, context, repo_url, pr_number)

    async def send_status(self, update: Update):
        session = self.host.load_session()
        if not session:
            await update.message.reply_text("ℹ️ No active session in memory.")
            return

        if "demand" not in session:
            repo_url = session.get("repo_url")
            quota_section = await asyncio.to_thread(self.host.get_model_quota_summary)
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

        quota_section = await asyncio.to_thread(self.host.get_model_quota_summary)
        mode = session.get("mode", self.host.MODE_EASY)
        label = "Hard (Thorough Review)" if mode == self.host.MODE_HARD else "Easy (Fast)"

        status_msg = (
            f"🧠 <b>Aegis Session Memory:</b>\n\n"
            f"📦 <b>Repository:</b> <code>{session.get('repo_url', 'N/A')}</code>\n"
            f"⚙️ <b>Mode:</b> <code>{label}</code>\n"
            f"💡 <b>Demand:</b> <code>{html.escape(session.get('demand', 'N/A'))}</code>\n"
            f"🌿 <b>Branch:</b> <code>{session.get('git_branch', 'N/A')}</code>\n"
            f"🏁 <b>Last Completed:</b> <code>{session.get('last_completed_step', 'N/A')}</code>\n\n"
        )
        if quota_section:
            status_msg += quota_section
        status_msg += "📊 <b>Step Statuses:</b>\n"
        pipeline_config = self.host.resolve_pipeline_config(mode=mode)
        for step in pipeline_config:
            step_name = step["step_name"]
            status = session.get("steps_status", {}).get(step_name, "pending")
            icon = "✅" if status == "success" else "🚫" if status == "aborted" else "❌" if status == "failed" else "⏳"
            status_msg += f"{icon} {step_name}: <code>{status}</code>\n"

        await update.message.reply_text(status_msg, parse_mode="HTML")

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if str(update.effective_chat.id) == self.host.ALLOWED_CHAT_ID:
            start_message = (
                "🤖 <b>Aegis Multi-Agent System Online</b>\n\n"
                "Send your demand with the desired execution mode:\n\n"
                "⚡ <b>Easy / Standard Mode</b> (Default — faster, skips Architect Reviewer, medium review reasoning):\n"
                "• <code>owner/repo: your demand</code>\n"
                "• <code>[easy] owner/repo: your demand</code>\n\n"
                "🛡️ <b>Hard / Complex Mode</b> (Thorough — includes Architect Reviewer validation & high review reasoning):\n"
                "• <code>[hard] owner/repo: your demand</code>\n"
                "• <code>owner/repo: [hard] your demand</code>\n"
                "• <code>owner/repo: difícil: your demand</code>\n\n"
                "<b>Available Commands:</b>\n"
                "• <code>/continue</code> - Resume paused/failed pipeline\n"
                "• <code>/status</code> - Check active task and quota status\n"
                "• <code>/stop</code> - Cancel currently running pipeline\n"
                "• <code>/clear</code> - Clear active session memory\n"
                "• <code>/review owner/repo#123</code> - Review an existing GitHub PR"
            )
            await update.message.reply_text(start_message, parse_mode="HTML")

    async def post_init(self, application: Application) -> None:
        """Registers slash commands in the Telegram client UI."""
        await application.bot.set_my_commands([
            BotCommand("start", "Start the bot and get instructions"),
            BotCommand("continue", "Resume the last paused/failed pipeline step"),
            BotCommand("status", "Query current pipeline status and memory"),
            BotCommand("stop", "Stop the current running pipeline"),
            BotCommand("clear", "Clear active session memory"),
            BotCommand("review", "Review an existing GitHub PR"),
        ])

    def build_application(self) -> Application:
        """Builds and returns the Application instance with registered handlers and post_init."""
        token = os.environ.get("TELEGRAM_BOT_TOKEN")
        if not token:
            raise ValueError("TELEGRAM_BOT_TOKEN is not defined in environment variables.")

        # concurrent_updates(True) is required so that commands like /stop are
        # processed while a long-running pipeline is still executing. Without it,
        # python-telegram-bot handles updates sequentially and /stop would be queued
        # behind the running pipeline, never firing task.cancel() mid-run.
        app = ApplicationBuilder().token(token).concurrent_updates(True).post_init(self.post_init).build()
        app.add_handler(CommandHandler("start", self.start))
        app.add_handler(CommandHandler("continue", self.handle_continue))
        app.add_handler(CommandHandler("status", self.handle_status))
        app.add_handler(CommandHandler("stop", self.handle_stop))
        app.add_handler(CommandHandler("clear", self.handle_clear))
        app.add_handler(CommandHandler("review", self.handle_review))
        app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), self.handle_demand))
        return app
