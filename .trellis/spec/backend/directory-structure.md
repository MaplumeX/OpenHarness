# Directory Structure

> How backend code is organized in this project.

---

## Overview

OpenHarness is a monorepo with three main code trees: a Python backend (`src/openharness/`), a Python personal-agent app (`ohmo/`), and two frontend apps (`frontend/terminal/`, `autopilot-dashboard/`). Build config and tooling live at the repo root.

---

## Directory Layout

```
openharness/                      # repo root
├── src/openharness/              # Main Python package (224 files, 24 modules)
│   ├── cli.py                   # Typer CLI entry (2424 lines)
│   ├── __main__.py              # python -m openharness support
│   ├── api/                     # LLM provider clients, auth, usage tracking
│   ├── auth/                    # Authentication flows, credential storage
│   ├── autopilot/               # Repo autopilot service (queue, scan, tick)
│   ├── bridge/                  # Remote session bridge
│   ├── channels/               # Chat integrations (Slack, Telegram, Discord, etc.)
│   ├── commands/               # Slash-command registry
│   ├── config/                 # Settings, schema, paths, output styles
│   ├── coordinator/            # Coordinator mode, agent definitions
│   ├── engine/                 # Query engine, stream events, cost tracking
│   ├── hooks/                  # Hook lifecycle (load, execute, hot-reload)
│   ├── keybindings/            # Keybinding parser, resolver
│   ├── mcp/                    # Model Context Protocol client
│   ├── memory/                 # Memory directory manager
│   ├── output_styles/          # Output style loader
│   ├── permissions/            # Permission checker, modes
│   ├── personalization/        # Rules engine, extractor, session hooks
│   ├── plugins/                # Plugin lifecycle, loader, installer
│   ├── prompts/                # System prompt builder, CLAUDE.md loading
│   ├── sandbox/                # Docker sandbox backend
│   ├── services/               # Cron scheduler, session storage, LSP, OAuth
│   ├── skills/                 # Skill loader, registry
│   ├── state/                  # App state, store
│   ├── swarm/                   # Multi-agent swarm (team, worktree, mailbox)
│   ├── tasks/                  # Task manager, shell/agent tasks
│   ├── themes/                 # Theme loader
│   ├── tools/                  # 40+ tool implementations (bash, read, write, etc.)
│   ├── ui/                     # TUI app, React launcher, backend host
│   ├── utils/                  # Filesystem, shell, helpers, network guard
│   ├── vim/                    # Vim mode transitions
│   └── voice/                  # Voice mode, streaming STT
├── ohmo/                        # Personal-agent subpackage (9 files)
│   ├── cli.py                  # Typer CLI entry
│   ├── runtime.py              # ohmo REPL and print-mode runtime
│   ├── gateway/                # Gateway service (router, bridge, config)
│   └── ...                     # prompts, memory, session_storage, workspace
├── frontend/terminal/          # Ink 5 + React 18 terminal UI (TypeScript)
├── autopilot-dashboard/        # Vite + React 19 web dashboard (TypeScript)
├── tests/                      # Python test suite (mirrors src/openharness/)
│   ├── conftest.py             # Shared fixtures
│   ├── test_api/               # Mirrors src/openharness/api/
│   ├── test_engine/            # Mirrors src/openharness/engine/
│   └── ...                     # One test dir per source module
├── scripts/                    # Install scripts, E2E smoke tests
├── docs/                       # Documentation (quick-start, architecture)
├── assets/                     # Static assets
├── pyproject.toml              # Python project config (hatchling, ruff, mypy, pytest)
└── .github/workflows/          # CI: ci.yml, autopilot-*.yml
```

---

## Module Organization

Each module under `src/openharness/` follows the same internal pattern:

- **Public API in `__init__.py`** — re-exports the main classes/functions for the module.
- **Domain logic in named files** — e.g. `api/client.py`, `api/errors.py`, `api/registry.py`.
- **Subpackages for complex domains** — e.g. `swarm/` contains `in_process.py`, `subprocess_backend.py`, `worktree.py`, `mailbox.py`, etc.

New features are added as a new subdirectory under `src/openharness/` with the same internal structure. See `channels/` as a well-organized example — it has a bus/events system plus per-channel implementations.

---

## Naming Conventions

| Type | Convention | Example |
|------|-----------|---------|
| Python modules | `snake_case` | `session_storage.py`, `file_lock.py` |
| Python classes | `PascalCase` | `ToolResultBlock`, `ErrorEvent`, `SwarmLockError` |
| Test directories | `test_<module>` | `test_api/`, `test_engine/` |
| Test functions | `test_<behavior>` | `test_work_secret_roundtrip` |
| CLI entry points | kebab-case or short aliases | `openharness`, `oh`, `ohmo` |

---

## Examples

Well-organized modules to reference as templates:

- **`src/openharness/api/`** — clean separation: `client.py` (Anthropic), `openai_client.py`, `copilot_client.py`, `errors.py`, `registry.py`, `provider.py`.
- **`src/openharness/swarm/`** — complex domain with clear file-per-concern: `team.py`, `worktree.py`, `mailbox.py`, `lockfile.py`, plus backends `in_process.py`, `subprocess_backend.py`.
- **`tests/test_bridge/`** — concise test module with both sync and async tests, parametrized cases.
