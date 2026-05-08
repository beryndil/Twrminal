# Feature 4 closeout — Inspector (5-tab + context meter)

**Closed:** 2026-05-08T01:23:22Z
**Closer session:** 522b9d0c40ab487bb8f70b92036b5fa2
**Verifier session:** 0cbd67a3 (re-verified HEAD 2026-05-08; 0 still-open / 0 fixed-since / 0 superseded)
**Executor sessions:** none — the only finding was fixed inline by the auditor at audit time (commit `bf1d7df`)

## Re-verification context

Feature 4 was formally CLOSED in the May-7 register (commit `bf1d7df`). Verifier 0cbd67a3
re-verified at HEAD on 2026-05-08 and found zero regressions. Verifier notes: 8-tab inventory
(5 original + Files / Changes / Metrics added since May-7 — growth, not regression); TokenMeter
wired in ConversationHeader; 9 cited code paths intact; zero post-fix commits touch inspector
frontend regressively.

## Findings register

| ID | Verdict | Status | Commit | Notes |
|---|---|---|---|---|
| feature-04-001 | FIXED_INLINE | DONE | `bf1d7df` | `evaluated_rules` eval chain missing from InspectorRouting.svelte — schema column, model field, and DB wiring existed; UI rendering was absent. Fixed inline at audit time: chain now renders in "Why this model?" expandable with skipped rules muted, matched rule highlighted. |

## Behavior-spec coverage

Primary spec: `docs/behavior/chat.md` §"Inspector pane (non-routing subsections)" (line 274+)

End-to-end behaviors verified:

1. **Tab-sticky persistence across page reloads** — spec: active tab persisted to `localStorage`
   under `bearings-v1:inspector-tab`; re-hydrated on boot; inactive tabs hidden via HTML `hidden`
   attribute (not unmounted), preserving per-tab transient state.
   Code path: `frontend/src/lib/components/inspector/Inspector.svelte:106` (`inspectorStore.activeTabId`)
   + lines 158–179 (all 8 tabs mounted with `hidden={activeTabId !== INSPECTOR_TAB_*}`).
   Test: `Inspector.test.ts`.

2. **TokenMeter wired in ConversationHeader (billing-mode swap)** — spec: header band shows
   context-window / cost indicator; subscription billing mode renders TokenMeter component,
   PAYG renders dollar figure.
   Code path: `frontend/src/lib/components/conversation/ConversationHeader.svelte:69`
   (import TokenMeter) + line 325 (rendered inside billing-mode conditional).
   Test: `ConversationHeader.test.ts:414` ("renders TokenMeter and hides the dollar figure
   when billing mode is subscription").

3. **evaluated_rules eval chain in Inspector Routing tab** — spec: "Why this model?" expandable
   renders the ordered rule evaluation chain; skipped rules shown muted, matched rule highlighted.
   This was the single finding fixed in `bf1d7df`.
   Code path: `frontend/src/lib/components/inspector/InspectorRouting.svelte:417–424`
   (`evaluated_rules` array rendered with `routingTimelineEvalChainLabel` heading; per-rule
   rendering with `i`-indexed match detection).
   Test: `InspectorRouting.test.ts`.

## Defect-typology cross-check

| Class | Instances in feature 4 | Resolved by |
|---|---|---|
| Module exists, unwired | 1 — `evaluated_rules` DB column + model field existed; InspectorRouting.svelte did not render the eval chain | commit `bf1d7df` |
| All other classes | 0 | — |

## Outstanding concerns

None. Verifier confirmed no regressions against current HEAD. All 8 tabs present and tested.
The 3 tabs added since May-7 (Files, Changes, Metrics) are additive growth, not spec violations —
the original spec referred to "5-tab" as the audited baseline; the additions have their own
behavior spec sections in `chat.md` §"Inspector pane".

## Sign-off

Feature 4 is **CLOSED**. The single finding (feature-04-001) was fixed inline at audit time
(commit `bf1d7df`). Re-verified at HEAD by verifier 0cbd67a3 on 2026-05-08: 0 regressions,
all cited code paths intact, 8-tab inventory confirmed.
