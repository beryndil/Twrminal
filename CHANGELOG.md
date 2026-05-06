# Changelog

All notable changes to this project are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

`commitizen` writes new sections automatically when you run `uv run cz bump`. Editing this file by hand is allowed but rare — usually only to refine a generated entry's wording.

## [Unreleased]

## [0.1.0] - 2026-05-05

### Added

- **§7 Foundation** — bootstrap layer for Bearings v1. Loads config from env, configures structured logging, installs the global exception handler, applies SQLite schema migrations, exits cleanly. No web layer, no agent integration.
- `src/bearings/config.py` — `pydantic-settings` `Settings` class with `BEARINGS_` env prefix; fields: `app_name`, `environment`, `log_level`, `log_json`, `data_dir` (XDG-default), `db_filename`. `db_path` composed property.
- `src/bearings/log.py` — `structlog` factory with PII-redaction processor and ConsoleRenderer/JSONRenderer toggle by environment.
- `src/bearings/errors.py` — global `sys.excepthook` that logs uncaught exceptions structurally and exits non-zero (Op: Zero-Crash, fail-fast at boundaries).
- `src/bearings/db/` — async DB layer:
  - `connection.py` — `open_connection` and `connect` async-context-manager applying `foreign_keys=ON`, `journal_mode=WAL`, `synchronous=NORMAL` PRAGMAs.
  - `migrations.py` — hand-rolled versioned migration runner discovering `NNNN_label.sql` files, tracking applied versions in `schema_version`, idempotent.
  - `migrations/0001_initial.sql` — `app_meta` key/value table.
  - `queries/` — empty per-resource query-module package (populated in §8).
- `src/bearings/app.py` — async `_bootstrap` wiring config → log → errors → DB migrations; sync `main()` wraps it via `asyncio.run`.
- `tests/` — 18 tests covering config, log, errors, app bootstrap, and DB migration runner. Autouse fixtures isolate `BEARINGS_*` env vars, cwd, and `data_dir` per test.
- `pyproject.toml` — hatchling build, full ruff/mypy/pytest/coverage/commitizen tool tables. `aiosqlite>=0.20` added on top of the python-base baseline.
- `.pre-commit-config.yaml` — hygiene + ruff + gitleaks + mypy + 400-line file cap + commitizen on commit-msg.
- `.gitignore`, `.gitattributes`, `.env.example` (with `BEARINGS_*` keys), `LICENSE` (MIT), `CONTRIBUTING.md`, `SECURITY.md`, `README.md`, `CLAUDE.md`.

### Source

Skeleton lifted from `~/Projects/templates/python-base` and adapted: package renamed `python_base → bearings`, env prefix `APP_ → BEARINGS_`, `aiosqlite` dependency added, DB layer + migration runner introduced, app bootstrap rewritten to async.

[Unreleased]: https://github.com/Beryndil/bearings/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Beryndil/bearings/releases/tag/v0.1.0
