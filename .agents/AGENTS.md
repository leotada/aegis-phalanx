# Agent Guidelines & Rules

This document outlines the operational guidelines and rules that all AI agents operating within this workspace must strictly follow.

## 1. Primary Rule: English Language Only
* **All Communications**: Write all comments, documentation, commit messages, and Pull Request titles/descriptions exclusively in **English**.
* **Code and Tests**: All variable names, function names, classes, test cases, and comments inside code files must be written in **English**.

## 2. Test-Driven Development (TDD) Workflow
* Always follow the TDD loop:
  1. **RED**: Write the test first. Run the test suite to ensure it fails.
  2. **GREEN**: Write the minimal amount of code required to make the test pass.
  3. **REFACTOR**: Clean up the code while ensuring the test suite remains passing.
* Do not finalize a task without complete test coverage verifying the requested behavior.

## 3. Git and Pull Request Standards
* Use **Conventional Commits** for all commits (e.g., `feat: ...`, `fix: ...`, `test: ...`, `refactor: ...`).
* Keep branches isolated under `feature/` namespaces.
* Document the Pull Request implementation, architecture, and test execution details clearly in the PR body.

## 4. Code Quality & Security
* Adhere to SOLID design principles.
* Ensure all database calls utilize parameterized queries or ORM abstractions.
* Never commit secrets (API keys, Telegram bot tokens, GitHub tokens) to the git repository. Use environment variables.

## 5. Development environment
* Use podman compose to manage the development environment (with space).