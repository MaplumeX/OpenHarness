# Quality Guidelines

> Code quality standards for backend development.

---

## Overview

OpenHarness enforces quality through:
- **Ruff** for linting (line length 100, target Python 3.11)
- **mypy** for type checking (strict mode)
- **pytest** for testing with asyncio support
- **CI** on GitHub Actions

---

## Forbidden Patterns

| Pattern | Reason |
|---------|--------|
| Bare `except:` | Always catch `Exception` or more specific types |
| `print()` for logging | Use `logging` module instead |
| f-strings in log calls | Use `%s`-style formatting with log methods |
| Letting exceptions escape query engine | Convert to `ErrorEvent` or `ToolResultBlock` |
| Storing secrets in code | Use environment variables or credential storage |

---

## Required Patterns

| Pattern | Details |
|---------|---------|
| Module-level logger | `log = logging.getLogger(__name__)` at top of each module |
| Type hints on public APIs | All public functions/methods should have type annotations |
| Pydantic for config/validation | Use Pydantic v2 models for structured data |
| Async tests with `@pytest.mark.asyncio` | Async test functions need the decorator |

---

## Testing Requirements

### Test Framework

- **pytest 8+** with `pytest-asyncio` (auto mode)
- Tests live in `tests/` directory mirroring `src/openharness/` structure
- Shared fixtures in `tests/conftest.py`

### Running Tests

```bash
uv run pytest -q                    # Quick test run
uv run pytest --cov=src/openharness # With coverage
```

### Test Patterns

```python
# Sync test
def test_work_secret_roundtrip():
    secret = WorkSecret(...)
    assert encode_work_secret(secret) == decode_work_secret(encoded)

# Async test
@pytest.mark.asyncio
async def test_spawn_session_and_kill(tmp_path: Path):
    handle = await spawn_session(session_id="s1", command="sleep 30", cwd=tmp_path)
    assert handle.process.returncode is None
    await handle.kill()

# Parametrized test
@pytest.mark.parametrize("input,expected", [(...), (...)])
def test_parser(input, expected):
    ...
```

### Test Naming

- Test directories: `test_<module>/` matching `src/openharness/<module>/`
- Test functions: `test_<behavior>`

---

## Code Review Checklist

From `.github/PULL_REQUEST_TEMPLATE.md`:

- [ ] `uv run ruff check src tests scripts`
- [ ] `uv run pytest -q`
- [ ] `cd frontend/terminal && npx tsc --noEmit` (if frontend touched)
- [ ] Add/update tests when behavior changes
- [ ] Update docs when CLI flags/workflows change
- [ ] Add changelog entry under `Unreleased`

---

## Linting and Type Checking

### Ruff (Linting)

```toml
# pyproject.toml
[tool.ruff]
line-length = 100
target-version = "py311"
```

Run: `uv run ruff check src tests scripts`

### mypy (Type Checking)

```toml
# pyproject.toml
[tool.mypy]
python_version = "3.11"
strict = true
```

Run: `uv run mypy src/openharness`

Note: Full strict mypy is not yet required for all files, but new code should aim for strict compliance.

---

## CI Pipeline

`.github/workflows/ci.yml` runs on every PR:

- Python tests on Python 3.10 and 3.11
- Ruff linting
- Frontend TypeScript check (`npx tsc --noEmit`)

---

## Common Mistakes

- **Skipping type hints** — annotate all public functions
- **Not running tests locally** — always run `uv run pytest -q` before pushing
- **Large PRs** — keep PRs scoped and small
- **Missing changelog entries** — add entry under `Unreleased` in changelog
