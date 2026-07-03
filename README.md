# Aegis Phalanx

An isolated, multi-agent TDD (Test-Driven Development) pipeline controlled via a Telegram bot. It runs in a rootless Podman sandbox and orchestrates official agent CLIs (`agy`, `cursor`, `claude`, or `aider`) through a configurable pipeline.

---

## Features

- **TDD Workflow**: Enforces tests first — production code is only added to satisfy failing tests (Red-Green-Refactor).
- **Pluggable Agent CLI**: Select the tool via `AGENT_TOOL` in `.env`. The image installs only that CLI; volume mounts and auth are generated automatically.
- **Flexible Git Authentication**: HTTPS cloning (`GITHUB_TOKEN`) or SSH cloning (dedicated key mounted read-only into the container).
- **Multi-Model Orchestration**: Six specialized steps defined in `agents/pipeline.py`. `AGENT_TOOL` selects one CLI for the entire run; per-step `model` and `reasoning_budget` from the config are passed to each adapter (adapters may ignore them).
  1. **Architect** (Planning — PLAN): `gemini-3.1-pro`, high reasoning, 5m timeout.
  2. **Test Developer** (Testing — RED): `gemini-3.5-flash`, medium reasoning, 10m timeout.
  3. **Developer** (Implementation — GREEN): `gemini-3.5-flash`, medium reasoning, 10m timeout.
  4. **Code Reviewer** (Review — PLAN): `gemini-3.5-flash`, high reasoning, 10m timeout.
  5. **Refactoring Developer** (Refactoring — REFACTOR): `gemini-3.5-flash`, medium reasoning, 10m timeout.
  6. **GitOps** (Documentation and PR): `gemini-3.5-flash`, low reasoning.

  How each `AGENT_TOOL` uses the config above:

  | Tool | CLI invoked | Models / reasoning |
  |------|-------------|------------------|
  | `agy` | `agy --model "Gemini … (Budget)"` | Per-step model and reasoning from the pipeline |
  | `cursor` | `agent -p … --model auto --trust --force` | Always `auto`; pipeline model/reasoning ignored |
  | `claude` | `claude -p … -y` | Pipeline model/reasoning ignored |
  | `aider` | `aider --model … --message …` | Per-step `model` passed to `--model`; reasoning ignored |

---

## Prerequisites

- **Podman** and `podman compose` on the host.
- A **Telegram Bot Token** ([@BotFather](https://t.me/BotFather)).
- Your **Telegram Chat ID** ([@userinfobot](https://t.me/userinfobot)).
- **Git credentials** (one of):
  - GitHub Personal Access Token (`GITHUB_TOKEN`), or
  - Passphrase-less SSH key (e.g. `~/.ssh/id_aegis`) added to GitHub.

---

## Installation & Setup

### 1. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env`:

```env
GITHUB_TOKEN=your_github_token_here   # Leave blank if using SSH
TELEGRAM_BOT_TOKEN=12345:AABBBCCC
TELEGRAM_CHAT_ID=your_chat_id_here
DEFAULT_REPO=owner/repo               # Optional default repository
AGENT_TOOL=cursor                     # agy | cursor | claude | aider
```

Changing `AGENT_TOOL` requires a rebuild: `make build`.

### 2. Authenticate the agent CLI

| `AGENT_TOOL` | Authentication | Session paths mounted into the container |
|--------------|----------------|----------------------------------------|
| `agy` | `agy login` on the host | `~/.config/antigravity`, `~/.gemini/*`, `~/.antigravity` |
| `claude` | `claude auth login` on the host | `~/.config/claude` |
| `cursor` | `CURSOR_API_KEY` in `.env` **or** `agent login` on the host | `~/.cursor`, `~/.config/Cursor` |
| `aider` | API keys in `.env` (provider-specific) | — |

`make build` / `make up` reads `AGENT_TOOL` from `.env`, renders `compose.tool.yml`, and passes the tool as a Containerfile build arg so only that CLI is installed in the image.

#### Using Cursor CLI (`AGENT_TOOL=cursor`)

**Option A — API key (recommended for containers)**

No Cursor CLI required on the host. Works with an active Cursor subscription.

1. Create a User API Key at [cursor.com/dashboard/integrations](https://cursor.com/dashboard/integrations).
2. Add to `.env`:
   ```env
   AGENT_TOOL=cursor
   CURSOR_API_KEY=your_key_here
   ```
3. Build and start:
   ```bash
   make build
   ```

**Option B — Host session login**

1. Install and log in on the host (credentials are bind-mounted into the container):
   ```bash
   curl -fsSL https://cursor.com/install | bash
   agent login
   ```
2. Set `AGENT_TOOL=cursor` in `.env` and run `make build`.

The pipeline invokes `agent --print "<prompt>" --model auto --trust --force`. Pipeline model/reasoning fields are ignored for Cursor. PR reviews use `--mode ask` instead of `--force` (see [PR review](#pr-review-review)).

Verify inside the running container:

```bash
podman exec agent_workspace agent --print "say hi" --model auto --trust --force
```

### 3. Configure SSH key authentication (optional)

If you use SSH instead of `GITHUB_TOKEN`:

```bash
ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_aegis
```

Add `~/.ssh/id_aegis.pub` to GitHub. `compose.yml` mounts the key read-only at `/root/.ssh/id_aegis`.

### 4. Start the stack

```bash
make build    # First run or after changing AGENT_TOOL
make up       # Subsequent starts
```

This starts only the **agent** container by default. The PostgreSQL database (`agent_postgres`) is **opt-in** — start it when a task needs a database:

```bash
make db-up    # Start the database container
make db-down  # Stop the database container
```

The agent connects via `postgresql://admin:admin@db:5432/appdb` when the database is running.

Or manually:

```bash
python3 scripts/render_compose_overlay.py
podman compose --env-file .env -f compose.yml -f compose.tool.yml up -d --build
podman compose --env-file .env -f compose.yml -f compose.tool.yml --profile db up -d db  # optional
```

### 5. Activate the bot

Send `/start` in your Telegram chat. The bot confirms the system is online.

### 6. Send a demand

The workspace is isolated inside the container — specify which repository to clone.

**Explicit repository prefix (recommended):**

```text
owner/repository_name: Create a User entity with SQLAlchemy. Write Pytest tests for persistence and email validation.
```

**With full URL:**

```text
https://github.com/owner/repository_name.git: Create a User entity...
```

**Without prefix** (uses `DEFAULT_REPO` from `.env`, or the last repository from session memory):

```text
Create a User entity using SQLAlchemy. Write Pytest tests to verify database persistence.
```

---

## Makefile commands

| Command | Description |
|---------|-------------|
| `make build` | Render `compose.tool.yml`, build image, start agent container |
| `make up` | Render overlay and start agent container |
| `make down` | Stop the stack (agent and database, if running) |
| `make db-up` | Start the optional PostgreSQL database container |
| `make db-down` | Stop the PostgreSQL database container |
| `make restart` | Re-render overlay and restart |
| `make logs` | Follow agent container logs |
| `make status` | Show container status |
| `make test` | Run test suite with coverage (≥99%) |

---

## Development

Project configuration lives in `pyproject.toml` (pytest and coverage settings).

Install test dependencies on the host:

```bash
pip install -e ".[test]"
make test
```

---

## Session memory & resuming tasks

On failure, state is persisted to `~/.config/aegis-phalanx/session.json` (mounted from the host).

### Commands

- `/continue` or `/resume` — Resume from the first failed/incomplete step.
- `/status` — Show step statuses, repository, branch, and demand.
- `/review` — Review an existing GitHub PR (see [PR review](#pr-review-review)).
- `/stop` — Cancel a running pipeline.
- `/clear` — Delete session memory.

### Natural language

The bot classifies intent using the active `AGENT_TOOL` CLI:

- *"continue"*, *"resume"*, *"continuar a tarefa"* → resume flow
- *"status"*, *"memória"* → show session details
- Anything else → new demand

Model quota usage (`/status`) is shown only when `AGENT_TOOL=agy`.

---

## PR review (`/review`)

Review an existing GitHub pull request without modifying the repository or posting comments. The bot clones the repo, checks out the PR branch, pre-fetches metadata and diff via `gh`, and runs a single review step with the active `AGENT_TOOL`.

### Usage

```text
/review owner/repo#123
```

Supported reference formats:

| Format | Example |
|--------|---------|
| `owner/repo#N` | `/review acme/api#42` |
| `owner/repo:N` or `owner/repo N` | `/review acme/api:42` |
| GitHub PR URL | `/review https://github.com/acme/api/pull/42` |
| PR number only | `/review 42` (requires `DEFAULT_REPO` in `.env`) |

### Requirements

- **`GITHUB_TOKEN`** — required for HTTPS clones (same as the TDD pipeline).
- **`gh` auth** — mounted from `~/.config/gh` on the host; used to check out the PR and fetch context before the agent runs.
- **`AGENT_TOOL`** — selects which CLI performs the review (rebuild after changing).

### Behavior by tool

| Tool | Review invocation | Notes |
|------|-------------------|-------|
| `agy` | `agy --model "Gemini 3.5 Flash (High)" …` | Per-step model and reasoning from `agents/review_pipeline.py` |
| `cursor` | `agent --print --mode ask --model auto --trust "<prompt>"` | Read-only ask mode; PR context is pre-fetched so the agent does not need `gh` |
| `claude` | `claude -p … -y` | Pipeline model/reasoning ignored |
| `aider` | `aider --model … --message …` | Per-step `model` passed to `--model` |

The review text is returned to Telegram only — no commits, file changes, or GitHub comments.

---

## Architecture

```
telegram_listener.py   # Telegram bot and pipeline orchestrator
agents/
  adapters/            # CLI adapters (agy, cursor, claude, aider)
  pipeline.py          # TDD step definitions
  review_pipeline.py   # PR review step definition
  registry.py          # Agent factory
  tool_specs.py        # Per-tool install commands and volume mounts
scripts/
  install_agent_tool.py       # Containerfile install helper
  render_compose_overlay.py   # Generates compose.tool.yml from .env
```
