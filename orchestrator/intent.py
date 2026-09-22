"""Classify a free-form Telegram message into a pipeline intent."""

from __future__ import annotations

import asyncio

from agents import AgentRegistry
from agents.config import AGENT_INTENT_TIMEOUT


class IntentClassifier:
    """Asks the active agent CLI what the user wants, then falls back to keywords."""

    async def classify(self, message_text: str, *, tool: str) -> str:
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
            agent_cli = AgentRegistry.get_agent(tool)
            cmd = agent_cli.build_command(
                prompt,
                "gemini-3.7-flash",
                "low",
                timeout=AGENT_INTENT_TIMEOUT,
            )
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _stderr = await process.communicate()
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


intent_classifier = IntentClassifier()
