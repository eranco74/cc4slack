# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

cc4slack is a Python app that bridges Claude Code's agentic capabilities to Slack. Users interact with Claude via Slack mentions or DMs, and each Slack thread maintains its own Claude Code SDK session with streaming responses, cost tracking, and session resume support.

## Build and Development Commands

```bash
# Setup
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Run the app
python -m src.main

# Tests
pytest                    # run all tests
pytest tests/test_foo.py  # run single test file
pytest -k "test_name"     # run tests matching pattern

# Linting and type checking
ruff check src
mypy src
```

## Architecture

The app uses Slack Bolt (async) with Socket Mode (no public URL needed) and the Claude Code SDK for agent queries.

**Request flow:** Slack event -> `slack/events.py` (command routing + event handlers) -> `claude/agent.py` (SDK query with streaming) -> `slack/message_updater.py` (progressive Slack message updates) -> `slack/actions.py` (button interactions: cancel/clear/status).

**Session model:** Each Slack thread maps to a `Session` (in `sessions/manager.py`) which tracks the Claude session ID, cost, turns, per-thread cwd, and per-thread permission mode. Sessions can be resumed across Slack threads and terminal via `connect` command.

**Permission enforcement:** The Claude Code SDK's headless mode auto-approves all tools regardless of `--permission-mode`, so permissions are enforced via `disallowed_tools` in `claude/agent.py:_run_query`. The `permission_mode` field maps to different `disallowed_tools` lists rather than relying on the SDK's permission system.

**Config:** Pydantic Settings in `config.py` loads from env vars / `.env` file. Key settings: `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`, `PERMISSION_MODE`, `WORKING_DIRECTORY`, `CLAUDE_MODEL`.

## Key Conventions

- Python 3.11+, async throughout
- Uses `structlog` for logging
- Ruff for linting (line-length=100, rules: E, F, I, N, W, UP)
- mypy strict mode
- `asyncio_mode = "auto"` for pytest-asyncio
- No tests directory exists yet (configured in pyproject.toml as `tests/`)
