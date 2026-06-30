# Aegis Phalanx

An isolated, multi-agent TDD (Test-Driven Development) pipeline controlled via a Telegram bot. It runs securely in a rootless Podman sandbox, orchestrating official CLI tools using dynamic models and reasoning levels.

---

## Features

- **TDD Workflow**: The pipeline enforces writing tests first, ensuring production code is only added to satisfy the tests (Red-Green-Refactor).
- **SSH & Git Agent Forwarding**: Native support for using host SSH keys and agent configurations inside the container securely without raw key exposures.
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
- A **GitHub Personal Access Token** with repository access (required for the GitHub CLI `gh`).
- An active **SSH Agent** on your host with your Git/GitHub SSH key loaded.

---

## Getting Started

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
SSH_AUTH_SOCK=/run/user/1000/gnupg/S.gpg-agent.ssh  # Adjust to your host agent path
```

### 3. Spin Up the Containers
Build and run the stack using Podman:
```bash
podman compose --env-file .env up -d --build
```
This commands builds the Fedora image with the required CLIs and starts the Telegram listener.

### 4. Activate the Bot
Go to your Telegram chat with the bot and send:
```text
/start
```
The bot will respond that the Multi-Agent System is online.

### 5. Send a Demand
Send any software engineering task to the bot. For example:
```text
Create a User database entity using SQLAlchemy. Write Pytest tests to verify database persistence and email format validation.
```
The bot will orchestrate the pipeline and send you real-time status updates, culminating in a Pull Request opened on your GitHub repository.
