# Aegis Phalanx

An isolated, multi-agent TDD (Test-Driven Development) pipeline controlled via a Telegram bot. It runs securely in a rootless Podman sandbox, orchestrating official CLI tools using dynamic models and reasoning levels.

---

## Features

- **TDD Workflow**: The pipeline enforces writing tests first, ensuring production code is only added to satisfy the tests (Red-Green-Refactor).
- **Secure Token Authentication**: Bypasses SSH passphrase prompts completely by dynamically cloning and pushing via HTTPS using your `GITHUB_TOKEN`.
- **Multi-Model Orchestration**:
  1. **Architect**: Planning and tests (RED phase) via `gemini-3.1-pro` (high reasoning).
  2. **Developer**: Implementation (GREEN phase) via `gemini-3.5-flash` (medium reasoning).
  3. **Code Reviewer**: Quality & Refactoring (REFACTOR phase) via `gemini-3.5-flash` (high reasoning).
  4. **GitOps**: PR details & GitHub CLI interactions via `gemini-3.5-flash` (low reasoning).

---

## Prerequisites

- **Podman** and `podman compose` installed on the host.
- A **Telegram Bot Token** (created via [@BotFather](https://t.me/BotFather)).
- Your personal **Telegram Chat ID** (retrieved via [@userinfobot](https://t.me/userinfobot)).
- A **GitHub Personal Access Token** with repository access (required for cloning, pushing, and GitHub CLI `gh` PR creation).

## Installation & Setup

### 1. Configure local sessions for official CLIs
Before running the container, make sure you have logged in to the CLIs on your host machine so the credentials can be mapped properly:
- For Claude Code: `claude auth login` (stores session in `~/.config/claude`)
- For Antigravity: `agy login` or equivalent configuration (stores session in `~/.config/antigravity`)

### 2. Configure Environment Variables
Copy `.env.example` to `.env` and fill in the values:
```bash
cp .env.example .env
```
Fill in the variables in `.env`:
```env
GITHUB_TOKEN=your_github_token_here
TELEGRAM_BOT_TOKEN=12345:AABBBCCC
TELEGRAM_CHAT_ID=your_chat_id_here
DEFAULT_REPO=owner/repo  # Optional default repository
```

### 3. Spin Up the Containers
Build and run the stack using Podman:
```bash
podman compose --env-file .env up -d --build
```
This command builds the Fedora image with the required CLIs and starts the Telegram listener.

### 4. Activate the Bot
Go to your Telegram chat with the bot and send:
```text
/start
```
The bot will respond that the Multi-Agent System is online.

### 5. Send a Demand
Send any software engineering task to the bot. Since there are no host folders mounted, you must specify which repository you want the agent to clone and work on. 

You can format your demand in two ways:

#### A. Explicit repository prefix (Recommended for targeting specific repositories):
```text
owner/repository_name: Create a User database entity using SQLAlchemy. Write Pytest tests to verify database persistence and email format validation.
```
*Example with full HTTPS URL:*
```text
https://github.com/owner/repository_name.git: Create a User database entity...
```

#### B. Direct demand (Uses the `DEFAULT_REPO` configured in your `.env`):
```text
Create a User database entity using SQLAlchemy. Write Pytest tests to verify database persistence and email format validation.
```

---

## Session Memory & Resuming Tasks

If a pipeline step fails (e.g. due to credentials issues or external timeouts), Aegis Phalanx automatically stores the execution state inside a persistent configurations file (`~/.config/aegis-phalanx/session.json`). This allows you to fix the issue and resume the task without starting from scratch.

### Commands

- `/continue` or `/resume`: Resumes the pipeline starting from the first failed/incomplete step.
- `/status`: Displays the status of each step, the active repository, the branch, and the demand description.
- `/clear`: Deletes the current session memory.

### Natural Language Resumption

You can also send standard text messages, and the bot will automatically classify your intent using Gemini 3.5 Flash:
- Asking the bot to *"continue"*, *"resume"*, or *"continuar a tarefa"* will trigger the resume flow.
- Asking *"what was the last thing done"*, *"status"*, or *"memória"* will display the active task details.
- Any other message will be interpreted as a new demand.

