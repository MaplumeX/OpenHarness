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

### UI Session Turn Queue

#### 1. Scope / Trigger

Use a UI session turn queue when an interactive runtime accepts line-like work while another
agent turn is active. The queue belongs at the UI/runtime boundary, not inside `engine/`, because
`QueryEngine` already owns conversation state and `run_query()` already owns the model/tool loop.

#### 2. Signatures

- Module: `src/openharness/ui/session_queue.py`
- Queue API: `SessionTurnQueue.enqueue(...)`, `dequeue()`, `remove(turn_id)`, `snapshot()`,
  `empty()`, and `len(queue)`.
- Protocol API: `BackendEvent(type="queue_snapshot", queue=SessionQueueSnapshot(...))`.

#### 3. Contracts

- Queue priorities are exactly `now`, `next`, and `later`; ordering is priority first, FIFO within
  the same priority.
- Queue kinds are line-like work only: `submit_line`, `apply_select_command`, and
  `synthetic_followup`.
- Queue snapshots expose `active`, `queued`, and `recent` turns with `id`, `kind`, `priority`,
  `state`, `label`, `created_at`, and `metadata`.
- Queued turns must execute through `src/openharness/ui/runtime.py::handle_line()` so slash
  commands, snapshots, command-triggered prompts, and `/continue` stay centralized.

#### 4. Validation & Error Matrix

- Missing `submit_line.line` -> emit a protocol error and do not enqueue.
- Missing `apply_select_command.command` or `.value` -> emit a protocol error and do not enqueue.
- Permission and question responses -> resolve their pending futures immediately; never enqueue
  them behind prompts.
- Interrupt -> cancel only the active turn; queued turns remain queued unless a separate clear or
  remove command exists.

#### 5. Good/Base/Bad Cases

- Good: busy UI receives a second user prompt, emits a queue snapshot, and drains the queued prompt
  after the active turn completes.
- Base: idle UI receives a prompt and executes it immediately through the same queued-turn executor.
- Bad: a UI host starts a second `QueryEngine.submit_message()` while a turn is still active.

#### 6. Tests Required

- Unit tests for priority order, FIFO within priority, removal, and snapshot ordering.
- Backend integration tests for busy enqueue, automatic drain, interrupt preserving queued turns,
  and immediate permission/question response handling.
- Protocol/UI tests or type checks for `queue_snapshot` payload compatibility.

#### 7. Wrong vs Correct

Wrong: using `BackgroundTaskManager` as the primary interactive prompt queue. Completed local-agent
restart does not preserve process-local interactive context.

Correct: keep session-turn ordering in `ui/session_queue.py`, then execute one turn at a time
through `handle_line()` and the existing `QueryEngine` / `run_query` path.

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
