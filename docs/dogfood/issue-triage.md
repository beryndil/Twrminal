# Issue triage — dogfood window

This document defines how runtime issues surfaced during the v0.18.0 dogfood
window are categorized, decided on (fix now vs defer), and escalated back to
the orchestrator. It governs phase **B/C/D** of the master checklist (id
`0f6e4006fb1d4340bda9983af3432064`) — items B.1–B.2 produce the issue feed,
C.1–C.2 are the triage windows, and D.1 is the gate that consumes triage
state to decide whether v1.0.0 ships.

The build phase has the **audit cascade** (plan §"Audit cascade") to handle
code-quality gaps with full autonomy. Dogfood is different: the issue feed is
*runtime* (live service, real DB, real Dave-driven sessions), the surface is
*observable behavior*, and Dave is in the loop for severity calls. This
protocol slots into that loop without reusing the audit cascade's vocabulary
(`CLEAN` / `GAPS` / `K=5 halt`) — those concepts don't map.

## Issue feed

The dogfood window has four issue sources, in descending automation:

1. **Daily probe** (`scripts/daily_probe.py`, item B.1) — reachability +
   schema-shape sanity on the live `bearings-v1.service`. Logs to
   `~/.local/share/bearings-v1/probes/YYYY-MM-DD.log`. A `FAIL` line is an
   issue candidate.
2. **Differential probe** (`scripts/diff_probe.py`, item B.2) — structural
   divergence between v0.17.x (8787) and v1 (8788). Logs to
   `~/.local/share/bearings-v1/diff-probes/YYYY-MM-DD.log`. Divergence is
   informational by default; only *unexpected* divergence (not pre-classified
   as a v1-deliberate change) is an issue candidate.
3. **Days-1-7 review** (master item C.1) and **days-8-14 review** (item C.2)
   — Dave's manual review windows. Each window walks the probe logs, the
   journal (`journalctl --user -u bearings-v1.service`), and any Bearings
   session Dave used during the window. Issues observed here enter triage.
4. **Ad-hoc observation** — Dave (or any agent in a paired chat) hits a bug
   mid-flow. Issues land here outside the formal review windows; the same
   triage applies.

## Severity categorization

Each issue gets exactly one severity label: **P0**, **P1**, or **P2**. The
label is set at intake and only changes if new evidence revises it; the
revision is logged inline with the original.

### P0 — Dogfood-blocking

- Service-down (`bearings-v1.service` failed-state, port 8788 not listening,
  `/api/health` 5xx, daily probe `FAIL` on `/api/health`).
- Data-loss-class regression (sessions write but don't persist, migration
  corruption surfaced post-cutover, vault contents lost on restart).
- Regression vs v0.17.x on a parity-critical surface (a flow that worked in
  v0.17.x is broken in v1 and Dave can't complete it via any path).
- Differential probe shows an *unexpected* OpenAPI path-set delta that
  removes a v0.17.x endpoint Dave is actively using.
- Security: a localhost-only invariant breaks (port 8788 binds non-loopback,
  vault leaks plaintext, logs grow PII).

P0 halts dogfood — Dave does not continue using v1 with a known P0 open.
The 14-day clock pauses while a P0 is open and resumes when it lands.

### P1 — Wrong-but-workable

- Behavior diverges from `docs/behavior/<subsystem>.md` but the user can
  complete the flow via a documented or obvious workaround.
- Differential probe shows divergence on a surface that's *expected* to
  differ in v1 but the v1 shape is wrong against
  `docs/model-routing-v1-spec.md` or `docs/architecture-v1.md`.
- Performance regression noticeable in normal use (UI jank, streaming stall,
  >2× latency vs v0.17.x on a comparable call).
- Routing-decision wrong against the spec but the override path works
  (Dave has to re-pick the model; flow completes).
- Log-noise issue that obscures real signal (`ERROR` lines firing on
  successful paths, traceback floods on benign 404s).

P1 doesn't halt dogfood. P1 enters the fix-or-defer rubric below.

### P2 — Polish

- Copy nits, contrast nits, alignment glitches.
- Missing-but-not-promised behavior (a UI affordance that would be nicer to
  have but isn't in the v0.18.0 spec).
- Edge-case console warnings that don't change observable behavior.
- Documentation drift in non-`behavior/` docs.

P2 never halts dogfood and never gates v1.0.0. P2 lands in `TODO.md` and
carries forward.

## Fix-or-defer rubric

Severity sets the *ceiling* on whether the issue can be deferred; the
rubric below decides where each issue actually lands.

| Severity | Default | Fix-now criteria | Defer criteria |
|---|---|---|---|
| **P0** | Fix now | Always — P0 means dogfood is paused. | Never. A P0 that "can't be fixed in the window" reclassifies as P1 only after the underlying cause is re-evaluated and the dogfood-blocking property is shown to no longer hold. |
| **P1** | Decide | Fix is **bounded** (lake, not ocean — see `~/.claude/rules/completeness-principle.md`); estimate ≤ 1 executor session; doesn't drag in unrelated subsystems; spec/behavior doc unambiguously says v1 is wrong. | Fix is unbounded; spec is itself ambiguous (file a behavior addendum first); v0.17.x had the same bug (parity, not regression — note this explicitly); fix would land safer in a v0.18.x point release than in the v1.0.0 cutover. |
| **P2** | Defer | Only if fixed incidentally while landing a P0/P1 in the same file — never as a standalone session. | Always — `TODO.md` only. |

The "bounded" check is the key call. A 50-line fix in one file with one new
test is bounded. A "while we're here, let's refactor the routing evaluator"
is unbounded. When in doubt, defer to a follow-up — the dogfood window
exists to *find* issues, not to absorb adjacent rewrites.

### Spec / behavior-doc disagreements

If triage hinges on whether the spec or a `docs/behavior/<subsystem>.md`
doc is itself wrong, the issue is *not* triaged as P0/P1/P2 first. Land
a behavior addendum (per plan §"Behavioral gap escalation") that resolves
the ambiguity, then re-classify the original issue against the corrected
doc. Skipping this step bakes the wrong call into the v1.0.0 record.

## Escalation path back to the orchestrator

The orchestrator (session `d4e89042507141f4a790a02459018152`) is largely
dormant during dogfood — phases A and B are done, and phases C and D are
mostly Dave-driven review. Runtime issues escalate through the **master
checklist**, not via a fresh audit cascade. The path differs by severity.

### P0 escalation (dogfood-pause path)

1. Triager opens a Bearings session titled `[P0] <one-line>`, tagged
   `dogfood`, `p0`, and the affected subsystem tag. Description plug
   captures: source (probe log line, journal grep, paired-chat
   transcript), observed vs expected, blast radius, the
   `bearings-v1.service` state at observation.
2. The triage session is posted to the orchestrator's prompt endpoint as
   a `PAUSE` followed by the session id. This is the orchestrator's
   "Dave-posted PAUSE" halt condition (plan §"Legitimate orchestrator
   pauses"). The orchestrator stops dispatching anything else.
3. The triager appends a child item under the active phase row (C.1 or
   C.2 if mid-window, otherwise D.1) using
   `CHECKLIST_FOLLOWUP block=yes` (blocking child — phase row cannot be
   checked while it's open). Item label: `[P0] <one-line> →
   <session-id>`.
4. Fix lands in the linked session under the standard executor contract
   (verification gates, conventional commit, push). On `DONE`, the
   triager appends the post-fix probe log line to the session
   description as evidence and rechecks the child item.
5. Triager unposts the orchestrator pause (`continue` to the prompt
   endpoint). The 14-day dogfood clock resumes.

### P1 escalation (fix-or-defer path)

1. Triager opens a Bearings session titled `[P1] <one-line>`, tagged
   `dogfood`, `p1`, and the subsystem tag. Description plug captures
   source, evidence, and the rubric call (which row of the table above
   applied, with reasoning).
2. **Fix-now branch.** Append a child item under the active review row
   (C.1, C.2, or D.1) using `CHECKLIST_FOLLOWUP block=yes`. Label:
   `[P1] <one-line> → <session-id>`. The orchestrator is *not* paused —
   P1 doesn't halt dogfood — but the phase row can't close until the
   child does. Fix lands under the standard executor contract.
3. **Defer branch.** Append a non-blocking follow-up using
   `CHECKLIST_FOLLOWUP block=no`. Label: `[P1-deferred] <one-line>`.
   Add a `TODO.md` entry citing the triage session id and the deferral
   rationale (which "Defer criteria" cell from the rubric applied).
   The deferred item is *not* a child of the current phase — it lives
   at the end of the master checklist and gates only the v1.0.0 tag
   call (D.2) if D.1 promotes it.
4. The orchestrator is informed of P1s only at phase boundaries: when
   the triager checks the phase row (C.1, C.2) the orchestrator
   inspects the child set and the deferred-list and dispatches the next
   review. No pause, no audit cascade.

### P2 escalation (TODO.md path)

1. Append a `TODO.md` entry. Format: `- <one-line> (P2, <subsystem>,
   observed YYYY-MM-DD)`. No Bearings session, no checklist item.
2. The orchestrator never sees P2. The post-1.0 backlog reaps the
   `TODO.md` P2 set after v1.0.0 ships.

### When the orchestrator escalates back

The reverse path exists for one case: the orchestrator's 5-cycle audit
circuit-breaker (plan §"Audit cascade") fires during a P0 fix-now or
P1 fix-now session. That's a build-phase failure inside a dogfood-phase
fix; it routes to the planning session
(`129d17c158db4e87ab4d8f873c6e9d64`) per the standard halt protocol,
not back through this triage doc. The planning session decides whether
the original triage call was right or whether the issue needs
re-classification.

## Final-readiness gate (D.1) consumption

D.1's done-when criteria are:

- **Every P0 in the dogfood window has been resolved.** A resolved P0
  has a closed child item under its triage phase row, a probe-log
  evidence line, and a commit on `v1-rebuild`.
- **Every P1 is either resolved or explicitly deferred.** A deferred
  P1 has a `[P1-deferred]` follow-up at checklist-tail and a `TODO.md`
  entry citing the deferral rationale. D.1 reads each deferred entry
  and either confirms the deferral (carries to v1.0.x backlog) or
  promotes it back to fix-now (appends a blocking child under D.1
  itself).
- **P2s are not gated.** D.1 confirms the `TODO.md` P2 list parses and
  carries it into the v1.0.x backlog. No fix is required to ship.

If D.1 promotes any P1 back to fix-now, it appends the blocking child
and the v1.0.0 tag call (D.2) waits. This is the only path by which a
"deferred" call gets reversed; once D.2 fires and v1.0.0 is tagged, the
deferral is locked.

## Cross-references

- Master checklist: `0f6e4006fb1d4340bda9983af3432064`
- Orchestrator session: `d4e89042507141f4a790a02459018152`
- Planning session: `129d17c158db4e87ab4d8f873c6e9d64`
- Daily probe: `scripts/daily_probe.py`, log dir
  `~/.local/share/bearings-v1/probes/`
- Differential probe: `scripts/diff_probe.py`, log dir
  `~/.local/share/bearings-v1/diff-probes/`
- Decision vocabulary: `~/.claude/rules/decision-discipline.md`
- Completeness rubric (lake vs ocean): `~/.claude/rules/completeness-principle.md`
- Audit cascade (build-phase, not dogfood): plan §"Audit cascade"
- Behavioral gap escalation: plan §"Behavioral gap escalation"
