"""Persist pipeline session metadata to a JSON file."""

from __future__ import annotations

import json
import os

from agents.pipeline import MODE_EASY
from orchestrator.paths import SESSION_FILE_PATH


class SessionStore:
    """Reads and writes the JSON file that remembers the last pipeline run."""

    def __init__(self, path: str = SESSION_FILE_PATH):
        self.path = path

    def save(
        self,
        repo_url: str,
        demand: str,
        last_completed_step: str,
        steps_status: dict,
        git_branch: str,
        session_file_path: str | None = None,
        mode: str = MODE_EASY,
    ) -> None:
        """Saves the current pipeline session metadata to a JSON file."""
        path = self.path if session_file_path is None else session_file_path
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            data = {
                "repo_url": repo_url,
                "demand": demand,
                "mode": mode,
                "last_completed_step": last_completed_step,
                "steps_status": steps_status,
                "git_branch": git_branch,
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            print(f"Error saving session: {e}", flush=True)

    def load(self, session_file_path: str | None = None):
        """Loads the pipeline session metadata from JSON file. Returns None if it doesn't exist."""
        path = self.path if session_file_path is None else session_file_path
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading session: {e}", flush=True)
            return None

    def clear(self, session_file_path: str | None = None) -> None:
        """Clears the active task session details but retains the last repo URL."""
        path = self.path if session_file_path is None else session_file_path
        # Late-bound so tests can patch orchestrator.session.load_session.
        session = load_session(path)
        if session and "repo_url" in session:
            try:
                data = {"repo_url": session["repo_url"]}
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=4)
            except Exception as e:
                print(f"Error clearing session: {e}", flush=True)
        else:
            if os.path.exists(path):
                try:
                    os.remove(path)
                except Exception as e:
                    print(f"Error clearing session: {e}", flush=True)

    def delete(self, session_file_path: str | None = None) -> None:
        """Removes the persistent session file completely (including repo URL)."""
        path = self.path if session_file_path is None else session_file_path
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception as e:
                print(f"Error deleting session file: {e}", flush=True)


session_store = SessionStore()


def load_session(session_file_path: str = SESSION_FILE_PATH):
    """Module-level alias so session clearing can be patched in tests."""
    return session_store.load(session_file_path)
