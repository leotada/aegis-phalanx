import copy
import os

from agents.config import DEFAULT_AGENT_TOOL
from agents.tool_specs import validate_tool

PR_REVIEW_CONFIG = [
    {
        "step_name": "PR Reviewer",
        "tool": "agy",
        "model": "gemini-3.5-flash",
        "reasoning_budget": "high",
        "timeout": "10m",
        "prompt": (
            "Act as a Staff Engineer code reviewer. Review Pull Request #{pr_number} "
            "in repository {repo_owner_name}.\n\n"
            "Use `gh pr view {pr_number} --repo {repo_owner_name}` to read the PR title, "
            "description, and metadata.\n"
            "Use `gh pr diff {pr_number} --repo {repo_owner_name}` to read the full diff.\n\n"
            "Analyze the changes for correctness, edge cases, test coverage, code quality, "
            "security, maintainability, and alignment with the PR description.\n\n"
            "Do NOT modify any files, create commits, push changes, or post comments to GitHub.\n"
            "Return ONLY your written review. No preamble, no postamble, and no instructions "
            "to run other commands."
        ),
    }
]


def resolve_review_pipeline_config(tool: str | None = None) -> list[dict]:
    """Return PR review steps with the active agent tool applied."""
    selected_tool = validate_tool(tool if tool is not None else os.environ.get("AGENT_TOOL", DEFAULT_AGENT_TOOL))
    return [{**copy.deepcopy(step), "tool": selected_tool} for step in PR_REVIEW_CONFIG]
