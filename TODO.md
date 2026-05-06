# bearings TODO

Append in the moment work is deferred / errors are passed on / something should have been done but wasn't (per global TODO discipline).

## Foundation (§7) — landed in 0.1.0

- [x] Project skeleton lifted from `python-base`.
- [x] `pydantic-settings` config loader with `BEARINGS_` env prefix.
- [x] `structlog` setup with PII-redaction processor.
- [x] Global `sys.excepthook` with fail-fast exit code.
- [x] `aiosqlite` connection helpers + versioned migration runner.
- [x] `0001_initial.sql` creating `app_meta`.
- [x] App bootstrap wired to apply migrations and exit cleanly.
- [x] 18 tests, full coverage gate green.

## Web layer + sessions CRUD (§8) — landed in 0.2.0

- [x] `fastapi` + `httpx` deps; `aiosqlite` already present.
- [x] `web/app.py` factory + middleware + exception handlers + dependency overrides.
- [x] Shared-token auth via `APIKeyHeader` + `secrets.compare_digest`; sentinel dependencies that raise loudly when unbound.
- [x] `web/logging.py` request-context middleware binding `request_id`; surfaces `X-Request-ID` response header.
- [x] `web/errors.py` stable `{"error": {...}}` envelope; `_serialise_validation_errors` filters non-JSON `ctx`.
- [x] `BearingsError` + `ConfigurationError` for boot-time fail-fast.
- [x] Config additions: `host`, `port`, `auth_token`, `auth_header_name`, `auth_disabled`.
- [x] `routers/health.py` unauthenticated probe.
- [x] `db/migrations/0002_sessions.sql` + `db/queries/sessions.py`.
- [x] `models/sessions.py` Pydantic shapes + `services/sessions.py` business logic + `routers/sessions.py` thin handlers.
- [x] 65 tests, 97% branch coverage.

## §8 follow-ups (deferred per plan)

- [ ] **Uvicorn server runner** — `app.py:main` currently constructs the app and exits. Wiring uvicorn into the entry point belongs with §13 graceful-shutdown work (SIGTERM/SIGINT handlers, WS close, log flush, aiosqlite close).
- [ ] **CORS** — Sec rule 6. No frontend yet → no origins to allow. Lands when §1/§4 frontend ships.
- [ ] **Rate limiting** — Sec rule 5. Localhost shared-token auth in v1 makes this lower-priority; lands as a `python-recipes` extraction when it shows up.
- [ ] **Security headers (X-Frame-Options, CSP, HSTS)** — Sec rule 10. Lands when frontend ships.
- [ ] **WebSocket auth** — Sec rule 9. Lands with §10 streaming work.
- [ ] **OpenAPI tightening** — security scheme, response examples, locked schema. Post-§8 polish.
- [ ] **Soft-delete + undo** — charter §21 DEFERRED. Hard-delete with confirm dialog at the UI layer.
- [ ] `_handle_http_exception` and `_handle_validation_error` carry an `isinstance` defensive narrow because Starlette's `add_exception_handler` types both args as `Exception`. Once Starlette ships precise generics for handlers, the narrow goes.

## Carry-overs from §6 charter sweep

- [ ] **§1 i18n** — string-externalization scaffold ahead of any UI strings landing (§8). EN + JA at v1. *§8 shipped without UI strings — moves to §1/§4 frontend phase.*
- [ ] **§13 Graceful Shutdown** — once §8 brings up FastAPI + WS connections, register SIGTERM/SIGINT handlers that close WS, flush logs, close aiosqlite, cancel auto-driver/sentinel tasks. *§8 shipped without uvicorn runner — handler wiring lands at §13 with the runner.*
- [ ] **§15 Dependency Security** — add `pip-audit` to `.pre-commit-config.yaml` once the dep set settles a bit. CI workflow gated to 1.0.0 per global CI Discipline.
- [ ] **§9 Help/About** — placeholder for the GitHub Issues link. *Carries forward into §1/§4 frontend work; web-layer surface alone has nowhere to render it.*

## Charter-template bug

- [ ] `~/.claude/templates/beryndil-charter.md` line 7 says "21 product-feature sections" but the file contains 28. Fix at the next charter-template revision so future `/init` sweeps don't inherit the miscount. (Logged in plan §6 too.)

## Foundation follow-ups (low priority)

- [ ] Consider extracting the migration runner to `python-recipes` once a second project needs it. Today the runner is small enough to live inline; recipe-extraction earns its keep at the second copy.
- [ ] `_load_applied_versions` returns `set[int]`; if migration count grows past a few hundred, switch to a streaming check (unlikely, but recorded).

## Distribution (§13)

- [ ] Decide remote (`Beryndil/bearings` likely) and push.
- [ ] Push branch protections + signed-commit policy when the repo goes public.
