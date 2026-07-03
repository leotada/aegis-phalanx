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
            "Act as a Staff Engineer code reviewer whose primary job is to find problems. "
            "Review Pull Request #{pr_number} in repository {repo_owner_name}.\n\n"
            "The PR branch is already checked out in this workspace. Use the pre-fetched "
            "context below as the primary source; inspect local files when needed to verify "
            "behavior, requirements, and business rules.\n\n"
            "{pr_context}\n\n"
            "Focus on actionable findings only. Prioritize, in this order:\n"
            "1. **Business-rule violations** — incorrect domain logic, missing or wrong "
            "validation, workflows that break stated requirements, or behavior that "
            "contradicts the PR description and established conventions in the codebase.\n"
            "2. **Technical issues** — bugs, race conditions, security vulnerabilities, "
            "data-integrity risks, error-handling gaps, breaking changes, and missing or "
            "inadequate tests for risky paths.\n"
            "3. **Important improvements** — changes that materially improve correctness, "
            "reliability, maintainability, or operability. Locate the repository's `AGENTS.md` "
            "conventions file if one exists (commonly at the repo root, or under `.agents/`, "
            "`.github/`, or `docs/`) and flag any changes that deviate from the standards, "
            "conventions, and guidelines documented there. Skip style nitpicks and optional "
            "refactors unless they prevent a real defect or violate AGENTS.md.\n\n"
            "For each issue found, state: severity (blocker / major / minor), location, "
            "what is wrong, and a concrete fix suggestion.\n"
            "If you find no issues in a category, say so briefly. Do not pad the review "
            "with praise or generic advice.\n\n"
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
