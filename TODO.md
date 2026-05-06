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

## Carry-overs from §6 charter sweep

- [ ] **§1 i18n** — string-externalization scaffold ahead of any UI strings landing (§8). EN + JA at v1.
- [ ] **§13 Graceful Shutdown** — once §8 brings up FastAPI + WS connections, register SIGTERM/SIGINT handlers that close WS, flush logs, close aiosqlite, cancel auto-driver/sentinel tasks. Foundation today exits before any of those exist, so deferred.
- [ ] **§15 Dependency Security** — add `pip-audit` to `.pre-commit-config.yaml` once the dep set settles a bit. CI workflow gated to 1.0.0 per global CI Discipline.
- [ ] **§9 Help/About** — placeholder for the GitHub Issues link. Owned by §8 (web layer) but flagging now so it doesn't slip.

## Charter-template bug

- [ ] `~/.claude/templates/beryndil-charter.md` line 7 says "21 product-feature sections" but the file contains 28. Fix at the next charter-template revision so future `/init` sweeps don't inherit the miscount. (Logged in plan §6 too.)

## Foundation follow-ups (low priority)

- [ ] Consider extracting the migration runner to `python-recipes` once a second project needs it. Today the runner is small enough to live inline; recipe-extraction earns its keep at the second copy.
- [ ] `_load_applied_versions` returns `set[int]`; if migration count grows past a few hundred, switch to a streaming check (unlikely, but recorded).

## Distribution (§13)

- [ ] Decide remote (`Beryndil/bearings` likely) and push.
- [ ] Push branch protections + signed-commit policy when the repo goes public.
