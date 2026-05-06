# Changelog

All notable changes to this project are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

`commitizen` writes new sections automatically when you run `uv run cz bump`. Editing this file by hand is allowed but rare — usually only to refine a generated entry's wording.

## [Unreleased]

## [0.2.0] - 2026-05-05

### Added

- **§8 Web layer + auth + sessions CRUD** — FastAPI HTTP surface stacked on top of the §7 foundation. `curl` can now create / list / get / update / delete a session, all behind `X-Bearings-Token`, with structured logs per request.
- `src/bearings/web/` — HTTP layer:
  - `app.py` — `create_app(settings)` factory; validates auth config at boot (refuses empty token unless `auth_disabled=True`), wires middleware, exception handlers, and dependency overrides.
  - `auth.py` — `APIKeyHeader`-based shared-token gate using `secrets.compare_digest` for constant-time comparison. Sentinel dependency raises explicitly if the override isn't wired.
  - `errors.py` — stable `{"error": {"code", "message", ...}}` envelope for `HTTPException`, `RequestValidationError`, and the catch-all (Op: Zero-Crash; never leak stack traces).
  - `logging.py` — per-request middleware binding a UUID4 `request_id` to `structlog.contextvars`; emits `http.request.start` / `http.request.finish`; surfaces id back as `X-Request-ID`.
  - `db.py` — async-generator dependency yielding a per-request `aiosqlite` connection.
  - `routers/health.py` — `GET /api/health` (unauthenticated) returns `{status: ok, version: ...}`.
  - `routers/sessions.py` — POST/GET/list/PATCH/DELETE `/api/sessions`, router-level `Depends(require_auth)`.
- `src/bearings/db/migrations/0002_sessions.sql` — sessions table with UUID4 text PK, `kind` CHECK constraint, indexes on `(kind, created_at DESC)` and `created_at DESC`.
- `src/bearings/db/queries/sessions.py` — raw-SQL CRUD using `INSERT...RETURNING` and parameterized binds; returns dicts at the boundary.
- `src/bearings/models/sessions.py` — Pydantic `SessionKind` Literal, `SessionCreate` (extra=forbid + absolute-path validator), `SessionUpdate` (partial; `model_fields_set` semantics), `SessionResponse`, `SessionList`.
- `src/bearings/services/sessions.py` — composition layer. Mints UUID4 hex ids, filters PATCH payloads to a whitelist.
- `src/bearings/errors.py` — `BearingsError` base + `ConfigurationError` for fail-fast at the auth-config boundary.
- `src/bearings/config.py` — new fields: `host` (default 127.0.0.1), `port` (default 8788), `auth_token` (`SecretStr`), `auth_header_name` (default `X-Bearings-Token`), `auth_disabled` (dev-only escape).
- `src/bearings/app.py` — `_bootstrap` now constructs and returns the FastAPI app; uvicorn runner deferred to §13 graceful-shutdown work.
- `tests/web/` — full HTTP-layer test suite using `httpx.AsyncClient` via `ASGITransport`: health (200 + version + `X-Request-ID`), auth (missing/empty/wrong/correct token, sentinel dependencies, `auth_disabled` escape), sessions CRUD round-trip, pagination + kind filter, full negative-path discipline.
- `tests/services/test_sessions.py` — service-layer unit tests decoupled from HTTP.
- `pyproject.toml` — `fastapi>=0.115,<1` runtime dep; `httpx>=0.28,<1` dev dep.

### Source

Built on top of v0.1.0 §7 foundation; no churn to the foundation modules apart from `errors.py` (added `BearingsError` + `ConfigurationError`) and `config.py` (added auth + bind fields). Plan-of-record: `~/.claude/plans/bearings-v1-section-8.md`.

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

[Unreleased]: https://github.com/Beryndil/bearings/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/Beryndil/bearings/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Beryndil/bearings/releases/tag/v0.1.0
