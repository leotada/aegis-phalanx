# AGENTS.md

Operational notes for agents working in this repository. Project-wide rules
(English-only, TDD workflow, Conventional Commits, SOLID) live in
`.agents/AGENTS.md` and still apply.

## Cursor Cloud specific instructions

This is a single-file Python app: the orchestrator is `telegram_listener.py`
with tests in `test_telegram_listener.py`. There is no `requirements.txt` /
`pyproject.toml`; the dependency list lives inline in `Containerfile`
(`python-telegram-bot pytest pytest-xdist psycopg2-binary`).

### Dev environment
- Local dev uses a Python virtualenv at `.venv`. The startup update script
  creates it and installs the deps above. The `Makefile` `test` target runs
  `.venv/bin/pytest`, so keep the venv at `.venv`.
- `podman` / `docker` are NOT installed in the cloud VM, so the container path
  (`make build` / `make up` / `compose.yml`) does not run here. Use the `.venv`
  for tests and local runs instead.

### Test / run
- Tests: `.venv/bin/pytest` (or `make test`). All tests are pure/mocked and need
  no DB or network.
- Run the bot: `TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=... .venv/bin/python telegram_listener.py`.
  Without a valid token the app still boots fully and fails at Telegram `getMe`
  with `InvalidToken` — that is the expected "no creds" outcome and confirms the
  app initializes and reaches the network.
- There is no linter configured (no ruff/flake8/black config); there is no lint command.

### Full end-to-end (producing a PR) requires external credentials
The pipeline shells out to authenticated CLIs that are not available by default
in the cloud VM:
- Antigravity CLI (`agy`) with a logged-in Google/Gemini session.
- GitHub auth via `GITHUB_TOKEN` (HTTPS) or an SSH key, plus the `gh` CLI.
- A real `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`.
The core orchestration (`handle_demand` → `parse_demand` → `run_pipeline` over
the 6-step `PIPELINE_CONFIG`) can be exercised without these by mocking the CLI
boundaries (`asyncio.create_subprocess_exec`, `run_command_and_stream`,
`get_pr_url`, etc.), which is how `test_telegram_listener.py` validates it.

### Gotchas
- Session memory defaults to `~/.config/aegis-phalanx/session.json`. The
  container runs as root (`/root/.config/...`); running locally as a non-root
  user prints a harmless `Error saving session: Permission denied` and the
  pipeline continues regardless.
- `sanitize_environment()` drops the placeholder `GITHUB_TOKEN=your_github_token_here`
  on import, so leaving the `.env.example` placeholder behaves like "no token".
