# Aegis Phalanx

An isolated, multi-agent TDD (Test-Driven Development) pipeline controlled via a Telegram bot. It runs securely in a rootless Podman sandbox, orchestrating official CLI tools using dynamic models and reasoning levels.

---

## Features

- **TDD Workflow**: The pipeline enforces writing tests first, ensuring production code is only added to satisfy the tests (Red-Green-Refactor).
- **Flexible Authentication**: Supports both HTTPS cloning (using your `GITHUB_TOKEN`) and SSH cloning (using a dedicated passphrase-less key isolated within the container).
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
- **Authentication Credentials**:
  - For HTTPS cloning: A **GitHub Personal Access Token** with repository access.
  - For SSH cloning: A **passphrase-less SSH key** (e.g. `~/.ssh/id_aegis`) configured in your GitHub account.

## Installation & Setup

### 1. Configure local sessions for official CLIs
Before running the container, log in to the CLI matching `AGENT_TOOL` in `.env` (default `agy`):

| `AGENT_TOOL` | Host login | Session paths mounted into the container |
|--------------|------------|------------------------------------------|
| `agy` | `agy login` | `~/.config/antigravity`, `~/.gemini/*`, `~/.antigravity` |
| `claude` | `claude auth login` | `~/.config/claude` |
| `cursor` | `agent login` | `~/.cursor`, `~/.config/Cursor` |
| `aider` | API keys in `.env` (no session mount) | — |

Set `AGENT_TOOL` in `.env`, then run `make build` or `make up`. The Makefile renders `compose.tool.yml` and passes `AGENT_TOOL` as a build arg so only that CLI is installed in the image.

#### Using Cursor CLI (`AGENT_TOOL=cursor`)

1. **Install and log in on the host** (credentials are mounted into the container):
   ```bash
   curl -fsSL https://cursor.com/install | bash
   agent login
   ```
   Verify with `agent --version`. Session files under `~/.cursor` and `~/.config/Cursor` must exist before starting the stack.

2. **Configure `.env`**:
   ```env
   AGENT_TOOL=cursor
   ```
   Optional fallback when session mounts are unavailable (CI/headless):
   ```env
   CURSOR_API_KEY=your_key_from_cursor_dashboard
   ```
   Create a key at [cursor.com/dashboard/integrations](https://cursor.com/dashboard/integrations).

3. **Build and start** (rebuild required when switching tools). `make build` reads `AGENT_TOOL` from `.env` for both the image and `compose.tool.yml` volume mounts:
   ```bash
   make build
   ```

The pipeline invokes `agent -p <prompt> --model auto --trust --force`. Model and reasoning fields in the pipeline config are ignored for Cursor; the CLI always runs in `auto` mode.

### 2. Configure SSH Key Authentication (Optional)
If you wish to use SSH authentication instead of `GITHUB_TOKEN`:
1. Generate a dedicated passphrase-less SSH key specifically for the agent:
   ```bash
   ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_aegis
   ```
2. Copy the contents of `~/.ssh/id_aegis.pub` and add it to your GitHub account (Settings -> SSH and GPG keys) or as a Deploy Key on your target repository.
3. The `compose.yml` file is configured to mount this key to `/root/.ssh/id_aegis` and use the `GIT_SSH_COMMAND` environment variable to enforce its usage inside the container.

### 3. Configure Environment Variables
Copy `.env.example` to `.env` and fill in the values:
```bash
cp .env.example .env
```
Fill in the variables in `.env`:
```env
GITHUB_TOKEN=your_github_token_here  # Leave blank if cloning via SSH
TELEGRAM_BOT_TOKEN=12345:AABBBCCC
TELEGRAM_CHAT_ID=your_chat_id_here
DEFAULT_REPO=owner/repo  # Optional default repository
AGENT_TOOL=cursor        # agy | cursor | claude | aider (rebuild with make build after changing)
```

### 3. Spin Up the Containers
Build and run the stack using the Makefile (reads `AGENT_TOOL` from `.env`):
```bash
make build
```
This renders tool-specific volume mounts and builds the image with only the selected CLI installed.

You can also run directly:
```bash
python3 scripts/render_compose_overlay.py
podman compose --env-file .env -f compose.yml -f compose.tool.yml up -d --build
```

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

#### B. Direct demand (Uses defaults/memory):
```text
Create a User database entity using SQLAlchemy. Write Pytest tests to verify database persistence and email format validation.
```
*Note: If no repository prefix is provided in the message, the bot will automatically fall back to the `DEFAULT_REPO` defined in your `.env` file. If `DEFAULT_REPO` is not defined, it will fall back to the **last used repository** stored in session memory.*

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

