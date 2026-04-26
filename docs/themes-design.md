# Themes & skins — design and scope

**Status:** Design only. Do not implement until Dave signs off on the
six decisions in §6.
**Owner:** Bearings session `Themes & skins — design + scope`
(plug `197df8d80e2c44d281452c2e89365679`).
**Last touched:** 2026-04-25.

## 1. Reality check (the brief was stale)

The originating brief described a Tier-0 codebase with "zero theming
infrastructure." That snapshot pre-dated the Midnight Glass commit
(`8b21a8e`) and the preferences-table migration (0026, commit
`2871877`). The actual current state is roughly **Tier 2 already
landed, Tier 2.5 partially wired**.

What ships today:

- `frontend/tailwind.config.js` — every used Tailwind color scale
  (`slate`, `sky`, `emerald`, `amber`, `rose`, `red`, `orange`,
  `teal`, `indigo`) is redefined via a `themed()` helper that
  resolves to `rgb(var(--bearings-<family>-<shade>) / <alpha-value>)`.
  Tailwind opacity modifiers (`/80`, `/60`) keep working.
- `frontend/src/lib/themes/tokens.css` — declares the channel triples
  for two themes: `midnight-glass` (active default, also bound to
  `:root` so unattributed elements still render) and `default` (saved
  snapshot of the pre-Midnight-Glass Tailwind palette).
- `frontend/src/lib/themes/midnight-glass.css` — non-color treatment
  (body aurora gradient, glass panels, button gradients, focus glow,
  active-row accent strip). All selectors scoped under
  `[data-theme='midnight-glass']`.
- `frontend/src/app.html` — `<html data-theme="midnight-glass">`
  hardcoded; `<meta name="theme-color">` set to the Midnight Glass
  base. A diagnostic reporter POSTs computed styles to
  `/api/diag/theme` for agent verification (still in place from the
  theming investigation; can be removed once this work closes).
- `frontend/src/app.css` — `@import`s both theme CSS files before the
  `@tailwind` directives.
- Migration `0026_preferences.sql` — singleton `preferences` table
  with a nullable `theme TEXT` column, explicitly reserved for "the
  themes session." NULL means "no preference set; render the server
  default."
- `frontend/src/lib/stores/preferences.svelte.ts` — reads/writes the
  server row, caches in localStorage for pre-network paint, and calls
  `applyTheme()` after every `apply()` to flip
  `document.documentElement.dataset.theme` to the saved value.
- `tailwind.config.js` keyframe `flashRed` (used by ContextMeter at
  ≥90%) pulls through `--bearings-red-*` tokens, so the pulse follows
  the active theme.

What's still missing — the actual scope of this session's
implementation work:

1. **No picker UI.** `Settings.svelte` (235 lines) has no theme
   control. The store will set the attribute if `theme` is non-NULL,
   but nothing ever writes a value, so the saved `default` palette
   ships unreachable.
2. **No no-flash boot.** `app.html` hardcodes `data-theme="midnight-glass"`.
   First paint always shows that theme; if the user's saved pref is
   `default`, they see a flicker on every reload while the
   preferences store boots, fetches, and re-applies.
3. **Hardcoded scrollbar colors.** `app.css` lines 33, 47, 53 use
   raw `#334155` / `#64748b`. They render the same regardless of
   active theme.
4. **Hardcoded search-mark colors.** `Conversation.svelte` lines
   2007–2012, `:global(mark.search-mark)`: yellow RGB literals
   (`rgb(234 179 8 / 0.35)` bg, `rgb(253 224 71)` fg). Doesn't shift
   with theme.
5. **Shiki theme hardcoded to `github-dark`** (`render.ts:5`).
   Wouldn't read well on a light theme; doesn't match Midnight Glass'
   warm-navy mood either.
6. **Only two palettes ship.** Both are dark. No light-mode user can
   pick light. `prefers-color-scheme` is ignored.
7. **No re-render hook for active code blocks.** Any shiki strategy
   that swaps the theme at runtime needs to either (a) re-run
   highlighting on every cached message or (b) render shiki with
   variables so it reflows purely via CSS.

So this session's job is finishing-and-extending, not greenfield
design.

## 2. Token vocabulary — already locked, mostly

The bundled palettes use a Tailwind-shade vocabulary (`slate-50`
through `slate-950`, `sky-200..900`, etc.) — not a semantic-slot
vocabulary. That's a deliberate trade-off documented in
`tokens.css`: it lets every existing component class
(`bg-slate-900`, `text-emerald-400/80`, `border-sky-500`) keep
working unchanged when the theme flips. A semantic-slot rewrite
(`--color-bg-root`, `--color-accent-success`, etc.) would require
touching every component.

**Recommendation: keep the Tailwind-shade vocabulary as the source of
truth for v1.** Add a thin layer of *semantic aliases* on top so
future themes can reason about intent rather than re-deriving every
shade decision:

```css
/* Semantic aliases — derived from the shade tokens above. New themes
 * only need to override the shades; the aliases re-resolve. */
--color-bg-root: var(--bearings-slate-950);
--color-bg-surface: var(--bearings-slate-900);
--color-bg-elevated: var(--bearings-slate-800);
--color-bg-selected: var(--bearings-slate-700);
--color-border-default: var(--bearings-slate-700);
--color-border-strong: var(--bearings-slate-600);
--color-border-accent: var(--bearings-sky-500);
--color-text-primary: var(--bearings-slate-100);
--color-text-secondary: var(--bearings-slate-300);
--color-text-muted: var(--bearings-slate-400);
--color-text-inverse: var(--bearings-slate-950);
--color-accent-success: var(--bearings-emerald-500);
--color-accent-warn: var(--bearings-amber-500);
--color-accent-danger: var(--bearings-rose-500);
--color-accent-info: var(--bearings-sky-500);
--color-mark-bg: var(--bearings-amber-500);
--color-mark-text: var(--bearings-amber-100);
--color-scrollbar-thumb: var(--bearings-slate-700);
--color-scrollbar-thumb-hover: var(--bearings-slate-500);
--color-focus-ring: var(--bearings-sky-500);
--color-overlay-scrim: 0 0 0; /* alpha applied at use site */
```

This is roughly 20 aliases (not the brief's 30–40 — Bearings reuses a
small palette). New themes override the 50-ish shade variables; the
aliases re-resolve automatically. Components that use raw shades
keep working; components that adopt the aliases (the new spots:
scrollbar, search-mark, future high-contrast theme overrides) get
single-point control.

## 3. Theme list (proposed)

| Slug | Mood | Status |
|---|---|---|
| `midnight-glass` | Warm-navy + violet, glass panels, aurora body | Shipping (active default) |
| `default` | Tailwind-original slate + cyan, flat | Shipping (saved snapshot) |
| `paper-light` | Light cream-on-graphite, no glass, accessible-AA | **New, scope this session** |
| `solar-flare` (optional) | Warmer dark, amber-leaning | **Optional alt — defer** |

**Why `paper-light` and not "slate-light".** Light-mode users
explicitly don't want a slate-flavored aesthetic; they want crisp
paper-white with strong contrast. Authoring it as a separate theme
file (`paper-light.css`) lets us ship a non-glass treatment (no
backdrop-filter, no aurora, flat surfaces) without conditioning every
midnight-glass rule on `:not([data-theme='paper-light'])`.

**Why defer `solar-flare` / extra dark themes.** v1 should ship one
dark + one light + the saved Tailwind-default for users who want the
v0.x look. Three is enough to validate the picker UX. More can land
in v0.x+1 once theme authorship is exercised.

## 4. Implementation surface (scoped)

**Track A — Picker UI + persistence (highest user value).**
- Add a `<select>` (or radio group) in `Settings.svelte` bound to
  `preferences.theme`. Wire `update({ theme })` on change.
- The store already calls `applyTheme()` on apply, so the
  `data-theme` flip is automatic.
- Cost: ~30 lines of Svelte + a label and option list.

**Track B — No-flash boot.**
- Add a tiny inline `<script>` to `app.html` (before `%sveltekit.head%`)
  that reads `localStorage.bearings:preferences-cache`, parses
  `theme`, and sets `document.documentElement.dataset.theme` if
  non-null. Runs synchronously before first paint.
- Pair with a `<meta name="theme-color">` update from the same
  script — read the cached theme, swap the meta value to match.
- Cost: ~15 lines of inline JS, defensive (catch parse errors).

**Track C — Author `paper-light`.**
- New file `frontend/src/lib/themes/paper-light.css` — palette block
  in `tokens.css` plus a treatment file scoped under
  `[data-theme='paper-light']`.
- Treatment specifically *removes* Midnight Glass effects (no
  backdrop-filter on `aside`, no aurora on body, flat shadows). The
  scoping makes this easy: midnight-glass rules only fire when
  `data-theme='midnight-glass'`; paper-light is its own scope.
- Verify against WCAG AA at minimum (4.5:1 contrast for body text).
- Cost: half a day of palette tuning + treatment authorship +
  spot-check across MessageTurn / Inspector / SessionList /
  ContextMeter / Settings.

**Track D — Cleanup hardcoded colors.**
- `app.css` scrollbar block → reference `--color-scrollbar-thumb` /
  `--color-scrollbar-thumb-hover` aliases.
- `Conversation.svelte` `mark.search-mark` → reference
  `--color-mark-bg` / `--color-mark-text` aliases (with the alpha
  applied via `rgb(... / 0.35)`).
- Cost: ~10 lines.

**Track E — Shiki strategy.**
Two paths:

- **E1 — Bundle two shiki themes, swap at runtime.** Add
  `github-light` (or `min-light`) alongside `github-dark`; when the
  active `data-theme` flips, walk all `[data-bearings-code-block]`
  elements and re-run `highlighter.codeToHtml()` on their source. The
  source needs to be retained on the wrapper (today it's not — only
  the rendered HTML). Adds a re-render pass and a per-block source
  attribute.
- **E2 — Custom shiki theme that uses CSS variables.** Author a
  shiki theme JSON whose token colors are `var(--shiki-token-keyword)`
  / `var(--shiki-token-string)` etc., then declare those variables
  per-theme in `tokens.css`. Pure-CSS theme flip; no re-render.
  Requires a custom shiki theme file plus token-name mapping.

**Recommendation: E2.** It matches the rest of the architecture
(theme flip is a CSS attribute change, nothing else moves) and
avoids re-running highlighting on every theme switch. Higher upfront
cost but lower lifetime cost. Defer E1 unless E2 reveals a shiki
limitation we can't work around.

**Track F — `prefers-color-scheme` integration.**
- First-visit behavior: when `preferences.theme === null` AND no
  cache exists, the no-flash script (Track B) reads
  `window.matchMedia('(prefers-color-scheme: light)').matches` and
  sets `data-theme` to `paper-light` if true, else `midnight-glass`.
- Once the user picks a theme explicitly, the saved value wins
  forever; we don't keep tracking the OS setting.
- Cost: 3 lines added to Track B.

## 5. Out of scope (don't drift into these)

- User-authored themes / live HSLA picker (Tier 3 from the brief).
  Re-evaluate after v1 ships and we know how often the bundled set
  is enough.
- Spacing/density themes. Color only for v1.
- Font-family themes. Color only for v1.
- Branding (favicon / logo) per-theme. Keep one favicon; meta
  theme-color is the only chrome that flips.
- High-contrast theme. Worth doing eventually for a11y, but
  deferred — v1 should validate the alias layer before adding a
  fourth bundled theme that exercises it hardest.
- Removing the diagnostic reporter in `app.html`. That's a separate
  cleanup; do it after the theme switcher is working and we no
  longer need server-side computed-style snapshots.

## 6. Decisions Dave needs to make

1. **Bundled theme list.** Confirm v1 ships
   `midnight-glass` + `default` + `paper-light`, with `solar-flare`
   deferred. Or call out a different alt theme to author instead.
2. **Picker UX.** Settings dropdown (compact, fits the existing
   form), radio cards with mini-previews (more discoverable, more
   work), or a header quick-toggle (always-visible)? Recommend
   **Settings dropdown** for v1 — adds zero chrome, matches the
   existing prefs surface.
3. **No-flash boot.** Approve the inline-script approach in `app.html`?
   Recommend **yes** — flicker on reload is the most-noticed bug
   when users discover theming.
4. **Shiki strategy.** E1 (swap themes, re-render) or E2 (variable-
   driven shiki theme, pure-CSS flip)? Recommend **E2**.
5. **`prefers-color-scheme` on first visit.** Respect OS or always
   default `midnight-glass`? Recommend **respect OS**, but pin to
   the user's choice once they pick one.
6. **Cleanup scope.** Tracks D (scrollbar + search-mark) and the
   diagnostic-reporter removal — bundle into the same shipping unit
   as the picker, or land them separately? Recommend
   **bundle D, defer reporter removal** until after the picker is
   verified.

## 7. Sequencing (assuming all six recommendations land)

1. Track D (cleanup) — small, no UX surface, lands first as
   prep. ~30 min.
2. Track C (author `paper-light`) — palette + treatment file,
   verified against AA contrast spot-checks. ~half day.
3. Track E2 (variable-driven shiki) — author the theme JSON, wire
   variables, verify against both dark and light. ~half day.
4. Track A + B + F together — picker UI, no-flash inline script,
   `prefers-color-scheme` fallback. ~half day.
5. Browser verification across MessageTurn / Inspector / SessionList /
   ContextMeter / Settings / Conversation in all three themes.
   ~hour.

Total: ~2 working days. Ships behind a Settings toggle; no flag
needed.

## 8. Verify before merging

- All three themes render at WCAG AA for body text (manual contrast
  check is fine — no automated gate).
- No flash of unstyled (or wrong-themed) content on reload, in any
  of the three themes.
- Code blocks shift palette with the rest of the UI.
- Search-mark color reads against all three theme backgrounds.
- Saving a theme preference persists across reloads, browsers, and
  tabs (the existing `preferences` store already handles
  cross-tab via cache + GET-on-boot).
- ContextMeter `flash-red` keyframe still pulses correctly on
  `paper-light` (the keyframe pulls through tokens; verify the
  contrast holds against a light background — may need a separate
  red-channel triple in `paper-light`).

## 6.1 Sign-off (2026-04-25)

All six §6 decisions resolved against the design's recommended option.
Bounded scope on each, and `~/.claude/rules/decision-posture.md`
consistently picks the complete/recommended choice when scope is
bounded. Implementation rides session `197df8d8…` (the prereq+execute
pair point at the same session). Reasoning per item:

1. **Bundled theme list →** `midnight-glass` + `default` + `paper-light`.
   `solar-flare` deferred. Three palettes (one warm-dark, one classic-
   dark, one light) is enough to validate the picker UX and exercise
   the alias layer once. A second alt-dark adds variant-load without
   answering a UX question.
2. **Picker UX →** Settings dropdown. Adds zero new chrome, matches
   the existing prefs form, lowest cost. Radio cards with mini-
   previews remains a credible v0.x+1 polish if Settings-page
   discoverability proves weak in practice. Header quick-toggle is
   over-promotion for a setting most users touch once.
3. **No-flash boot →** Inline `<script>` in `app.html` per Track B,
   reading `bearings:preferences-cache` from localStorage and setting
   `document.documentElement.dataset.theme` synchronously before first
   paint. SSR doesn't apply (Bearings ships as a static SPA behind
   FastAPI; there's no server-rendered first paint to seed). Blocking
   stylesheet swap is the failure mode being avoided. Same script
   updates `<meta name="theme-color">`.
4. **Shiki strategy →** E2 — variable-driven shiki theme. Pure-CSS
   flip matches the rest of the architecture (theme change is a
   `data-theme` attribute mutation; nothing else recomputes). Higher
   upfront cost (custom shiki theme JSON + token-name mapping) but
   eliminates re-running highlighting on every theme switch and
   removes the "retain raw source on every code block" requirement
   E1 would impose. If E2 hits a shiki limitation we can't work
   around, fall back to E1 in a follow-up; do NOT mix strategies.
5. **`prefers-color-scheme` →** Auto-follow on first visit only.
   When `preferences.theme === null` AND no localStorage cache exists,
   the no-flash inline script reads
   `window.matchMedia('(prefers-color-scheme: light)').matches` and
   picks `paper-light` if true, else `midnight-glass`. Once the user
   picks any theme explicitly (including via the picker resetting to
   `default`), the saved value wins permanently — no continuous OS
   tracking. First-launch hint UI is unnecessary; the picker itself
   is the "you can change this" affordance.
6. **Cleanup scope →** Bundle Track D (scrollbar + search-mark color
   cleanups) into the v1 picker shipping unit. Track D is ~10 lines,
   tightly coupled to the alias layer being introduced, and shipping
   it without the picker would mean writing aliases that no theme
   actually exercises differently yet. Defer the
   `/api/diag/theme` reporter removal to a separate cleanup once the
   picker is verified across all three themes.

**Implementation track for this session:** Continue in session
`197df8d80e2c44d281452c2e89365679`. The follow-up checklist item
`[Execute] Themes & skins v1 picker — implement per §7 (197df8d8)`
points at the same session id; no fresh spawn needed.

**Sequencing locked to §7's order**: Track D → Track C → Track E2 →
(Track A + B + F together) → browser verification across all three
themes. ~2 working days, no flag.

## 9. Accessibility

### Reduced motion

Bearings honors the OS-level "Reduce motion" accessibility preference
(GNOME, KDE, Hyprland-via-portal, Windows, macOS). The guard lives in
`frontend/src/app.css` and applies to every element on the page:

```css
@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }
}
```

Two design notes worth pinning:

- **0.01ms, not 0s.** Some engines skip `transitionend` /
  `animationend` on a 0-duration value. Code that listens for those
  events (autoscroll latch, gutter chip pulse) keeps working with a
  perceptually-instant 0.01ms.
- **Component-level opt-back-in.** The global rule is intentionally
  aggressive — a component that needs to keep playing motion in
  reduced-motion mode supplies its own `@media (prefers-reduced-motion:
  reduce)` block that swaps the motion for a non-motion equivalent.
  Reference implementation: `BearingsMark.svelte` swaps its
  rotating-marker sweep for an opacity pulse so "working…" still reads
  visually without spinning geometry.

### Imperative scrolls

CSS can't reach `Element.scrollTo({ behavior: 'smooth' })` /
`Element.scrollIntoView({ behavior: 'smooth' })` — those API calls read
the `behavior` argument directly. The shared helper at
`frontend/src/lib/utils/motion.ts` exports `scrollBehavior()`, which
returns `'auto'` under reduced-motion and `'smooth'` otherwise. Every
imperative smooth-scroll call site routes through it (sidebar
session-bump, checkpoint-gutter jump, tool-call jump-to,
search-mark-into-view, context-menu jump-to-turn).

### Motion duration band (150-300ms)

Three CSS custom properties on `:root` in `tokens.css` codify the
allowed transition-duration band:

- `--motion-duration-fast` (150ms) — micro-interactions, button hover,
  focus crossfade. Default; matches Tailwind's `transition-*` floor.
- `--motion-duration-base` (200ms) — generic transitions where 150ms
  feels too snappy.
- `--motion-duration-slow` (300ms) — panel reveals, list reflows.
  Slowest motion in the band.

Component CSS should reference these tokens rather than hard-coding
millisecond values. Anything slower than 300ms is out of band —
escalate the design before introducing it. Theme treatments and
button-baseline transitions consume the tokens directly so a future
"calm UI" preference (e.g. uniformly stretching the band) lands in one
file.

### Verification

In a browser with "Reduce motion" enabled (or via Playwright launched
with `--reduce-motion=reduce`):

- Hover a button: no transform / box-shadow lift, base color flips
  instantly.
- Click a checkpoint chip: anchor message snaps to center without
  smooth scroll.
- Run a sidebar search: the first match snaps into view.
- Trigger a session-list bump (incoming WS event): the sidebar jumps
  to top instantly.

`window.matchMedia('(prefers-reduced-motion: reduce)').matches` should
report `true` in that browser. The `motion.test.ts` suite covers both
the reduced-motion and default branches plus the SSR-safe fallback.

## 10. Open follow-ups (deferred backlog)

These are noted so the next theming session has a clear backlog,
not embedded in this scope:

- High-contrast theme (a11y).
- User-authored themes (Tier 3).
- Per-theme `<meta name="theme-color">` driven by the live picker
  rather than only the no-flash script.
- Density / spacing themes.
- Removal of `/api/diag/theme` reporter once the picker is verified.

---

*See also:* `frontend/src/app.css`,
`frontend/src/lib/themes/tokens.css`,
`frontend/src/lib/themes/midnight-glass.css`,
`frontend/src/lib/utils/motion.ts`,
`frontend/src/lib/stores/preferences.svelte.ts`,
`src/bearings/db/migrations/0026_preferences.sql`,
`TODO.md` §"Theme switcher UI — 2026-04-23".
