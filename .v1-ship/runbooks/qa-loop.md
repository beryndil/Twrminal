# QA Loop runbook — Bearings v1 runtime bug-hunt

After the ship-readiness loop closes (all 14 features `closed`, 5 CCWs
`done`, 7 Analytics phases `done`), the orchestrator does NOT idle.
It pivots into Phase 2: runtime QA against the live app.

The audit-driven loop you just finished compared docs to code. Phase 2
compares **the running app to a user's experience.** Every feature
exercised in a real browser. Every button clicked. Every input typed.
Every output read. Every error path triggered. Findings filed as
runtime-bug entries; executors fix; QA re-tests.

## Inputs

- App URL: `http://127.0.0.1:8788` (the v1 server under audit).
- Feature inventory: `V1_FEATURE_AUDIT.md` Status table — same 14
  features. Their behavior specs at `docs/behavior/<name>.md` are the
  oracle: what "correct" means.
- Quality gate skills available locally: `playwright`, `lighthouse-ci`,
  `qc-verify-ui`, `qa-only`, `rss-sitemap-validate`,
  `json-ld-validate`, `dns-validate`, `secrets-scan`,
  `dependency-audit`.

## Roles

### Doctor (one-time, first action of Phase 2)
Runs `setup-doctor` skill + checks env. Confirms:
- v1 server alive at 127.0.0.1:8788 (HTTP 200 on `/`).
- Bearings UI alive at 127.0.0.1:8787 (this orchestrator's signaling).
- Playwright browsers installed (run
  `playwright-cli install` if missing).
- Lighthouse-ci CLI available (`npx @lhci/cli --version`).
- Frontend dist served matches HEAD (`git log -1 --oneline` on
  served path's commit ref, if available).
Outputs `.v1-ship/qa/preflight.md`. If any check fails, halt and
post the gap to Dave's session — this IS a Dave-blocking item.

### QA Surveyor (one per feature)
Drives the running app with Playwright. For feature N, exercises every
behavior documented in `docs/behavior/<spec>.md`. For each documented
behavior:
- Take a snapshot before.
- Drive the input (click, type, hotkey, navigate).
- Take a snapshot after.
- Capture: DOM diff, console messages, network requests, errors.
- Compare observed behavior to spec text.
- Emit one of: `OK` / `BUG` / `LAYOUT_POLISH` / `SPEC_AMBIGUOUS`.

### BUG vs LAYOUT_POLISH taxonomy (binding)

The Phase 2 termination contract is **"Dave sees only layout tweaks
on handoff."** That makes the BUG/LAYOUT_POLISH split decisive — it
determines what blocks termination vs what gets deferred.

**Classify as `BUG` (blocks termination, must fix in Phase 2):**
- A documented behavior produces wrong output (or no output).
- A documented input has no handler / wrong handler.
- A keyboard shortcut documented in `keyboard-shortcuts.md` fires the
  wrong action or no action.
- A console.error fires during normal use (not just edge cases).
- An API call returns a non-success status that the spec doesn't
  document as expected.
- A theme switch leaves un-themed elements (raw colors leaking
  through where tokens should apply).
- A modal / overlay traps focus, leaks focus, or fails Esc-to-close.
- An a11y violation classified by axe-core as `serious` or
  `critical`.
- Lighthouse perf < 90 on a route with documented perf budget.
- A network request 4xx/5xx that isn't a documented error path.
- A documented destructive action lacks the documented confirm step.
- Any data-loss or data-corruption path.
- Any auth / permission boundary failure.
- A spec'd feature that simply doesn't exist in the running app.

**Classify as `LAYOUT_POLISH` (does NOT block termination; deferred
to Dave's review):**
- Spacing / margin / padding choices.
- Font size / weight / hierarchy nuance.
- Color choices within the existing token palette (token A vs token
  B, both spec-compliant).
- Copy wording where multiple valid phrasings exist.
- Animation timing.
- Component density (compact vs comfortable).
- Empty-state illustrations.
- Visual polish on already-functional surfaces.

**SPEC_AMBIGUOUS** — the spec doesn't clearly say what should happen.
File a `docs/behavior/*.md` clarification finding; do NOT classify
as BUG. CCW-1's pattern applies.

The cap on layout polish: a survey may emit at most one
`LAYOUT_POLISH` per documented behavior. Repetitive layout nits across
many surfaces collapse into a single pattern entry. Do not flood the
deferred queue.

Output: `.v1-ship/qa/feature-NN-runtime.jsonl` (one entry per behavior)
+ `.v1-ship/qa/feature-NN-runtime.log` (Playwright trace + console
capture).

QA Surveyor is `claude-opus-4-7` (needs strong reasoning to compare
observed behavior to prose spec).

### Cross-cutting Surveyors (parallel with feature surveyors)
Specialized one-shot runs:
- **Accessibility** — Lighthouse a11y score on every route, plus
  axe-core violations from every page. `lighthouse-ci` skill.
- **Performance** — Lighthouse perf score, LCP, CLS, TBT on every
  route. Threshold: 90+ per CLAUDE.md project rule (when applicable).
- **Console-error sweep** — open every page, log every
  console.error / console.warn, classify as bug/noise.
- **Network sweep** — every API call from the app, assert 2xx (or
  documented 4xx/5xx for error paths).
- **Keyboard-only navigation** — close every modal, navigate every
  surface using only keyboard. Ties out to
  `docs/behavior/keyboard-shortcuts.md`.
- **Theme sweep** — exercise each theme, capture screenshots, look
  for un-themed elements (raw color literals, missing token
  applications).
- **Security & deps** — `secrets-scan`, `dependency-audit`,
  `security-scan` skills.

### QA Executor (one per BUG)
Same as ship-loop executor — implements one fix end-to-end. Reads the
runtime bug entry, identifies root cause from Playwright capture +
console logs + spec, fixes, runs gates, commits, pushes. Self-verifies
the fix by re-running the failing Playwright trace via the original
QA Surveyor's session id. (Surveyor confirms fix; if not fixed,
escalates back as DONE_WITH_CONCERNS.)

### QA Re-Surveyor (one per feature, after all its BUGs are DONE)
Re-runs the full Surveyor pass. If 0 BUGs, feature is QA-CLEAN. If
new BUGs surface (regressions or previously-missed), they queue.

## Phase 2 dispatch sequence

### Wave 0 — Preflight (sequential)
Doctor session. On PASS → Wave 1.

### Wave 1 — Cross-cutting surveys (parallel, read-only on app)
Accessibility, Performance, Console sweep, Network sweep, Keyboard
nav, Theme sweep, Security/deps. All run against the live app, none
modify code. ~7 sessions in flight; cap at 3 concurrent to avoid
overwhelming the app server.

### Wave 2 — Per-feature QA Surveys (parallel, read-only on app)
14 surveyors, one per feature. Same concurrency cap.

### Wave 3 — Bug execution (strict serial, same constraint as ship-loop)
For every BUG emitted by Wave 1 or Wave 2, dispatch an executor.
Severity-first: blocking bugs (broken core flows) → degraded UX
→ minor visual / copy.

### Wave 4 — Re-Survey (per-feature)
On all that feature's bugs DONE, re-survey. Repeat Wave 3 + 4 until
the feature returns 0 BUGs.

### Wave 5 — Final sign-off
When all 14 features QA-CLEAN (zero BUGs; LAYOUT_POLISH entries
collected separately) AND all cross-cutting reports green AND
Lighthouse a11y/perf/best-practices/SEO scores meet the documented
thresholds, emit `FINAL — Bearings v1 ship-ready` and idle.

**Dave handoff contract:**
- Functional state: every documented behavior in
  `docs/behavior/*.md` works as described in the running app.
- Console state: no errors, no warnings during normal use.
- Network state: every API call returns the documented status.
- Accessibility: zero serious/critical axe-core violations.
- Performance: Lighthouse meets project thresholds.
- Security: no critical findings from secrets-scan / dependency-audit
  / security-scan.
- The handoff message includes a `LAYOUT_POLISH` digest:
  `.v1-ship/qa/layout-polish-deferred.md` enumerating every
  layout/copy/aesthetic note collected across all Surveyors.
  This is the only thing Dave is expected to triage on handoff.

If any functional gate fails, Phase 2 does NOT terminate. The bug
queue remains open and the orchestrator continues dispatching
executors until clean.

## Tooling installs (Doctor responsibility)

```bash
# Playwright browsers (Doctor checks; installs on miss)
npx playwright install chromium firefox webkit

# Lighthouse-ci (Doctor checks; installs on miss)
npm install -g @lhci/cli  # or use npx, no global

# Verify Bearings v1 endpoint
curl -sf http://127.0.0.1:8788/ -o /dev/null && echo OK
```

If the v1 server isn't running:
```bash
# From repo root
cd /home/beryndil/Projects/active/bearings
.venv/bin/bearings serve --host 127.0.0.1 --port 8788 &
```

If browser binaries fail to install (sandbox / network issue), Doctor
logs the gap and Phase 2 cannot proceed — that's a Dave-blocking wall.

## Spawn protocol

Same as ship-loop: `POST /api/sessions` on Bearings 8787, runbook in
first prompt, tag_ids `[2, 11]`, model `claude-opus-4-7` for
Surveyors / Doctor, `claude-sonnet-4-6` for Executors.

## State

`.v1-ship/state.json` extends with `phase_2` block:
```json
{
  "phase_2": {
    "preflight": {...},
    "cross_cutting": {...},
    "feature_surveys": {...},
    "totals": {bugs_filed, bugs_fixed, features_qa_clean, ...}
  }
}
```

Same handoff protocol applies — orchestrator can rotate mid-Phase-2.

## Termination

All 14 features QA-CLEAN AND all cross-cutting green → emit
`FINAL — Bearings v1 ship-ready` AND notify Dave's session via
`POST /api/sessions/<DAVE_SESSION_OR_DEFAULT>/prompt` (this IS a
Dave-facing event — the app is ready for hand-off).

If a wall is hit (browser install failed, app server down, security
scan finds an unfixable critical), post BLOCKED to Dave's session
with the wall description and idle. This IS Dave-blocking by design.
