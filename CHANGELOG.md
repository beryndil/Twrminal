# Changelog

All notable changes to Bearings are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

The `1.0.0` tag is reserved for the stability commitment after roughly
two weeks of dogfood; pre-release versions continue under `0.x.y` per
SemVer §4.

## [Unreleased]

### Added

* **Differential probe v0.17.x ↔ v1** (master item B.2). New
  `scripts/diff_probe.py` is a stdlib-only differential probe that
  hits equivalent endpoints on the live v0.17.x service (loopback
  port 8787) and the v1 service (port 8788), then diffs structural
  shape and logs the deltas. Three diff modes cover the
  heterogeneous surface: `json_shape` (recursive type-skeleton diff
  for `/api/health`, `/api/sessions?limit=5`, `/api/tags`),
  `openapi_paths` ((METHOD, path) set diff for `/openapi.json` —
  the highest-leverage mode, surfacing every endpoint added /
  removed / renamed in v1), and `metric_names` (Prometheus
  `# HELP <name>` set diff for `/metrics`). Logs one JSONL record
  per probe plus a `SUMMARY` trailer to
  `~/.local/share/bearings-v1/diff-probes/YYYY-MM-DD.log` (mode
  0700, append). Exit 0 = both sides reachable on every probe,
  1 = any reachability failure. Shape divergence is informational
  (logged, not gated) — observing divergence over the cutover
  window is the point. Backed by 28 unit tests in
  `tests/test_diff_probe.py` covering shape extraction,
  shape diff, OpenAPI path-set diff, Prometheus parse, log
  serialisation, and end-to-end orchestration through a fake
  transport. The `[tool.mypy]` `mypy_path = "scripts"` entry in
  `pyproject.toml` is added in the same commit so the test's
  `TYPE_CHECKING` import resolves cleanly under
  `mypy --strict`; this also clears the pre-existing
  `import-not-found` baseline that `tests/test_cutover_smoke.py`
  inherited from item 3.4.
* **Daily probe + systemd-user timer** (master item B.1). New
  `scripts/daily_probe.py` is a stdlib-only health probe (no httpx
  / venv dependency) that hits `/api/health`, `/api/sessions?limit=5`,
  `/api/quota/current` (the headroom-conceptual surface — the literal
  `/api/usage/headroom` named in the done-when text doesn't exist in
  v1's route surface; see the script docstring for the swap), the
  paired `/api/quota/history`, `/openapi.json`, and `/metrics`. Logs
  one JSONL record per probe plus a `SUMMARY` trailer to
  `~/.local/share/bearings-v1/probes/YYYY-MM-DD.log` (mode 0700,
  append). Exit 0 = all PASS, 1 = any FAIL.
* **Probe systemd units.** `config/bearings-v1-probe.service`
  (oneshot, hardened identical to `bearings-v1.service`) and
  `config/bearings-v1-probe.timer` (daily 09:15 local, 5min jitter,
  `Persistent=true`). Install:
  `cp config/bearings-v1-probe.{service,timer} ~/.config/systemd/user/
  && systemctl --user daemon-reload
  && systemctl --user enable --now bearings-v1-probe.timer`.
  Both pass `systemd-analyze --user verify`.

## [0.18.0] — 2026-04-29

The v1 rebuild: behavioral parity with v0.17.x's feature surface, plus
model-routing v1, on a fresh tree (`v1-rebuild` branch, orphan
history). Concurrent run with v0.17.x is supported (port 8788, DB
`~/.local/share/bearings-v1/`, systemd unit `bearings-v1.service`).

### Added

* **Model routing v1** (per `docs/model-routing-v1-spec.md`):
  * `evaluate()` pure function for tag-rule + system-rule + default
    resolution (`agent/routing.py`).
  * Quota poller and `apply_quota_guard()` downgrade with manual-override
    accounting (`agent/quota.py`).
  * Override-rate aggregator with rolling 14-day window
    (`agent/override_aggregator.py`).
  * Routing / quota / usage HTTP endpoints per spec §9
    (`/api/routing/*`, `/api/quota/*`, `/api/usage/*`).
  * Per-message routing/usage columns on `messages` capturing executor
    and advisor `model_usage`, source, reason, matched rule.
  * `RoutingDecision`, `RoutingRule`, `SystemRoutingRule`, `QuotaSnapshot`
    frozen dataclasses (Appendix A wire shape).
* **Frontend routing surfaces** (per spec §6 + §10):
  * New-session dialog with reactive routing preview (300 ms debounce),
    advisor toggle, quota bars (yellow at 80 %, red at 95 %), and
    downgrade banner with "Use anyway" override.
  * Per-message `RoutingBadge` in the conversation pane.
  * Inspector **Routing** subsection: current decision, advisor totals,
    quota delta this session, per-message timeline with "Why this
    model?" expandable rule chain.
  * Inspector **Usage** subsection: 7-day headroom chart, by-model
    table, advisor-effectiveness widget, rules-to-review list (override
    rate > 30 % over 14 days).
  * Routing rule editor (per-tag + system-wide) with drag-reorder,
    enable/disable, duplicate, delete, and a deterministic
    test-against-message dialog (no LLM).
* **Inspector core** (per arch §1.2): five-tab inspector shell with
  Agent / Context / Instructions / Routing / Usage subsections (item
  2.5 ships the first three; 2.6 lights up Routing + Usage).
* **Paired chats + prompt endpoint + bearings CLI**:
  `POST /api/sessions/<id>/prompt` returning 202, paired-chat persistence
  per `docs/behavior/paired-chats.md`, and a `bearings` CLI with the
  `todo` subcommand.
* **Checklists, auto-driver, and sentinels**: full picking / linking /
  reordering / run-control endpoints; auto-driver agent surfaces
  per-item run state through the sidebar sentinel pip.
* **Vault + memories**: per-tag system-prompt overlays, vault search,
  memories editor, redaction toggles per `docs/behavior/vault.md`.
* **Themes**: theme provider with no-flash boot script, runtime picker
  with Midnight Glass / Default / Paper Light, theme-color meta updater.
* **Keyboard shortcuts and context menus**: keybinding registry with
  cheat-sheet, palette, and right-click action surface per
  `docs/behavior/keyboard-shortcuts.md` and `docs/behavior/context-menus.md`.
* **Migration script**: `scripts/migrate_v0_17_to_v0_18.py` copies
  v0.17.x DB to the v1 path, transforms schema, has dry-run mode, and
  is idempotent on re-run.
* **OpenAPI export**: `GET /openapi.json` (item 1.10) and the static
  copy at [`docs/openapi.json`](docs/openapi.json) — 62 paths,
  53 schemas.
* **Documentation**: `docs/architecture-v1.md`, `docs/model-routing-v1-spec.md`,
  per-subsystem behavior specs under `docs/behavior/`, augmented chat.md
  §"Inspector pane (non-routing subsections)", project `CLAUDE.md`.
* **Quality gates**: 12-tool pre-commit stack (ruff, mypy, pytest,
  vulture, radon, interrogate, codespell, pip-audit, eslint, prettier,
  svelte-check, knip, ts-prune, depcheck, lychee), playwright e2e,
  cross-system consistency lint, ≥ 80 % coverage on business logic.

### Changed

* **Repo posture**: `v1-rebuild` is an orphan branch; pre-commit
  `branch-verifier` rejects commits to any other branch on this
  worktree. Per-worktree `core.hooksPath` isolation via
  `scripts/setup-worktree.sh`.
* **Backend layout** consolidated per `docs/architecture-v1.md`:
  * `bearings.agent` collapses v0.17.x's three-file session split into a
    single session lifecycle module.
  * `bearings.web` separates DTOs (`web/models/`) from routes
    (`web/routes/`); each route group has a typed Pydantic wire model.
  * `bearings.config` exposes the spec-mandated numeric constants in a
    single constants module — no inline literals downstream.
  * `bearings.db` keeps a single routing-aware schema (no migration
    chain) and per-concern query modules.
* **Frontend layout**: `lib/components/` regrouped from v0.17.x's
  flat 60+ files into feature-scoped folders
  (`conversation/` + `sidebar/` + `inspector/` + `routing/` + `vault/`
  + `reorg/` + `menus/` + `modals/` + `feedback/` + `common/` +
  `pending/` + `checklist/` + `settings/` + `icons/`).
* **SDK**: pinned `claude-agent-sdk~=0.1.69` (compatible-release).
  Streaming protocol, advisor tool, beta headers, `model_usage` shape,
  effort levels, `fallback_model`, and subagent auto-select all updated
  to current SDK surface (see `docs/architecture-v1.md` §5 SDK currency
  audit).
* **Concurrent-run defaults** for v1 vs v0.17.x: port 8787 → **8788**;
  DB `~/.local/share/bearings/` → `~/.local/share/bearings-v1/`;
  systemd `bearings.service` → `bearings-v1.service`.

### Deferred (explicitly NOT in v0.18.0)

* Multi-user / auth — Bearings stays localhost.
* Cross-user shared rule libraries (per spec §12).
* ML routers, A/B testing, classifier preflight (per spec §12).
* Per-rule model-version pinning (per spec §12).
* `1.0.0` stability commitment — post-dogfood decision.

### Migration

Run the one-shot migration script after upgrading from v0.17.x:

```bash
uv run python scripts/migrate_v0_17_to_v0_18.py --dry-run
uv run python scripts/migrate_v0_17_to_v0_18.py
```

The script reads from `~/.local/share/bearings/sessions.db` and writes
to `~/.local/share/bearings-v1/sessions.db`. The v0.17.x install is left
untouched so the two services can run concurrently on ports 8787 / 8788
during cutover.

The migration coerces v0.17 session titles to fit v1's runtime
invariants:

* NULL or empty titles → ``"(untitled)"`` sentinel (the v1 ``Session``
  dataclass requires a non-empty title; the schema's NOT NULL alone is
  not sufficient).
* Titles longer than 500 chars are truncated with an ellipsis suffix
  so the row remains addressable through ``GET /api/sessions``.

### Cutover smoke

`scripts/cutover_smoke.py` is the v1 acceptance gate. It migrates a v0.17.x
DB into a tempdir target, boots the v1 FastAPI app + SvelteKit dist
against the migrated data, probes every API subsystem (health, metrics,
tags, sessions, vault, uploads, routing, quota, usage, diag, static
SPA), walks migrated rows back through the API to confirm round-trip
integrity, and runs the Playwright E2E suite (29 tests across 9
specs). The script emits a per-stage PASS / FAIL report and exits 0
only when every stage is green:

```bash
uv run python scripts/cutover_smoke.py             # full acceptance
uv run python scripts/cutover_smoke.py --skip-e2e  # fast iteration
uv run python scripts/cutover_smoke.py --json      # machine-readable
```

[0.18.0]: https://github.com/Beryndil/Bearings/tree/v1-rebuild
