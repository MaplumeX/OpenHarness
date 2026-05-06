# Backend Development Guidelines

> Best practices for backend development in this project.

---

## Overview

This directory contains guidelines for backend development. Each file documents the team's actual coding conventions extracted from the codebase.

---

## Guidelines Index

| Guide | Description | Status |
|-------|-------------|--------|
| [Directory Structure](./directory-structure.md) | Module organization and file layout | ✅ Filled |
| [Database Guidelines](./database-guidelines.md) | No database — file-based state patterns | ✅ Filled |
| [Error Handling](./error-handling.md) | Custom exceptions, retry patterns, error-to-stream conversion | ✅ Filled |
| [Quality Guidelines](./quality-guidelines.md) | Ruff, mypy, pytest, CI, code review | ✅ Filled |
| [Logging Guidelines](./logging-guidelines.md) | Python stdlib logging, %s-format, log levels | ✅ Filled |

---

## Quick Reference

- **Language**: Python 3.11 (target), 3.10+ supported
- **CLI Framework**: Typer
- **Validation**: Pydantic v2
- **Testing**: pytest with pytest-asyncio
- **Linting**: Ruff (line length 100)
- **Type Checking**: mypy (strict mode)
- **Logging**: Python stdlib `logging` module
- **State Storage**: File-based (JSON/YAML), no database

---

## Key Files

| File | Purpose |
|------|---------|
| `pyproject.toml` | Project config, dependencies, tool settings |
| `src/openharness/cli.py` | Main CLI entry point |
| `tests/conftest.py` | Shared test fixtures |
| `.github/workflows/ci.yml` | CI pipeline |

---

**Language**: All documentation is written in **English**.
