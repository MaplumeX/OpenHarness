# Database Guidelines

> Database patterns and conventions for this project.

---

## Overview

**This project does not use a database.** All persistent state is file-based (JSON/YAML files on disk). There is no ORM, no migrations, and no SQL.

---

## State Storage Patterns

| Storage Type | Location | Implementation |
|--------------|----------|----------------|
| Session storage | JSON files | `src/openharness/services/session_storage.py` |
| Workspace state | JSON/YAML files | `ohmo/workspace.py` |
| Gateway config | JSON files | `ohmo/gateway/config.py` |
| Memory | Markdown files | `src/openharness/memory/memdir.py` |
| Credentials | Keyring or filesystem | `src/openharness/auth/storage.py` |
| Autopilot state | File-based registry/journal | `src/openharness/autopilot/service.py` |
| Cron jobs | YAML/JSON files | `src/openharness/services/cron.py` |

---

## File-Based State Best Practices

When adding new persistent state:

1. **Use Pydantic models** for schema validation (e.g., `GatewayState`, `WorkSecret`).
2. **Atomic writes** — write to a temp file, then rename.
3. **Graceful degradation** — if read fails, start with empty/default state.
4. **No locking for reads** — files are assumed to be single-writer.

---

## Common Mistakes

- **Storing large binary data** — use external files and store paths instead.
- **Not handling missing files** — always check `Path.exists()` before reading.
- **Blocking I/O in async contexts** — use `aiofiles` or run in thread pool.
