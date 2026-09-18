"""Persist pipeline session metadata to a JSON file."""

from __future__ import annotations

import json
import os

from agents.pipeline import MODE_EASY
from orchestrator.paths import SESSION_FILE_PATH


def save_session(
    repo_url: str,
    demand: str,
    last_completed_step: str,
    steps_status: dict,
    git_branch: str,
    session_file_path: str = SESSION_FILE_PATH,
    mode: str = MODE_EASY,
) -> None:
    """Saves the current pipeline session metadata to a JSON file."""
    try:
        os.makedirs(os.path.dirname(session_file_path), exist_ok=True)
        data = {
            "repo_url": repo_url,
            "demand": demand,
            "mode": mode,
            "last_completed_step": last_completed_step,
            "steps_status": steps_status,
            "git_branch": git_branch,
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
