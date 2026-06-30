import copy
import os

from agents.config import DEFAULT_AGENT_TOOL
from agents.tool_specs import validate_tool

PIPELINE_CONFIG = [
    {
        "step_name": "Architect (Planning - PLAN)",
        "tool": "agy",
        "model": "gemini-3.1-pro",
        "reasoning_budget": "high",
        "timeout": "5m",
        "prompt": "Create a new git branch for the feature (switch/create if needed). Read this requirement: '{demand}'. Act as a Software Architect. Write a detailed plan containing all the business context, business rules, and design choices. The plan must contain two separate sections: 1) 'Test Specification Plan' detailing the test cases to be written, expected inputs/outputs, and edge cases for the Test Developer, and 2) 'Implementation Plan' describing the architectural design, file modifications, and guidelines for the Developer. Write this detailed plan to a file named `architect_plan.md` in the root of the repository. Do NOT write any tests or production code yet.",
    },
    {
        "step_name": "Test Developer (Testing - RED)",
        "tool": "agy",
        "model": "gemini-3.5-flash",
        "reasoning_budget": "medium",
        "timeout": "10m",
        "prompt": "Read the `architect_plan.md` file created by the Architect in the root of the repository. Act as a Test Developer. Strictly follow the 'Test Specification Plan' section to write and implement all the specified test cases. Run the tests via CLI and prove they fail (TDD RED Phase). Do NOT write any production code. Do NOT delete `architect_plan.md` as it is needed by the Developer in the next step.",
    },
    {
        "step_name": "Developer (Implementation - GREEN)",
        "tool": "agy",
        "model": "gemini-3.5-flash",
        "reasoning_budget": "medium",
        "timeout": "10m",
        "prompt": "Read the newly created tests that are currently failing and the `architect_plan.md` file in the root of the repository. Act as a Developer. Strictly follow the 'Implementation Plan' section of `architect_plan.md` to write the minimum and strictly necessary production code to make the tests pass (GREEN Phase). Run the tests until all of them pass perfectly. Run lint and other quality tools to ensure the code quality and fix any issues found. Do NOT delete `architect_plan.md` as it is needed by the Reviewer in the next step.",
    },
    {
        "step_name": "Code Reviewer (Review - PLAN)",
        "tool": "agy",
        "model": "gemini-3.5-flash",
        "reasoning_budget": "high",
        "timeout": "10m",
        "prompt": "Act as a Staff Engineer reviewer. Read the `architect_plan.md` file for context and analyze the recent changes. Are all the new important cases being covered with tests? Is the code clean, secure, and free of code smells? Do NOT modify the code or run refactoring. Instead, create a detailed refactoring plan listing all identified issues, code smells, and step-by-step refactoring/fixing instructions. Write this plan into a file named `refactor_plan.md` in the root of the repository. After the review, delete the `architect_plan.md` file.",
    },
    {
        "step_name": "Refactoring Developer (Refactoring - REFACTOR)",
        "tool": "agy",
        "model": "gemini-3.5-flash",
        "reasoning_budget": "medium",
        "timeout": "10m",
        "prompt": "Read the `refactor_plan.md` file created by the Code Reviewer in the root of the repository. Strictly follow and execute the plan of the code reviewer to fix and refactor the code. Do not perform any changes that are not in the plan. Ensure that the entire test suite continues to pass after your fixes. Once all fixes and refactoring are successfully done, delete the `refactor_plan.md` file.",
    },
    {
        "step_name": "GitOps (Documentation and PR)",
        "tool": "agy",
        "model": "gemini-3.5-flash",
        "reasoning_budget": "low",
        "prompt": "Commit all changes using the Conventional Commits pattern. Push the current branch to origin using `git push origin HEAD`. If the push fails, retry once. Note: The Pull Request will be created automatically by the system orchestrator, so you do NOT need to run `gh pr create` yourself.",
    },
]


def resolve_pipeline_config(tool: str | None = None) -> list[dict]:
    """Return pipeline steps with the active agent tool applied."""
    selected_tool = validate_tool(tool if tool is not None else os.environ.get("AGENT_TOOL", DEFAULT_AGENT_TOOL))
    return [{**copy.deepcopy(step), "tool": selected_tool} for step in PIPELINE_CONFIG]
