# Telemetry

Bearings is a single-operator, localhost-only tool. It is not instrumented to
report anything about you, your sessions, your prompts, your tool calls, your
costs, or your machine to any third party — including its author.

## What Bearings collects

**Nothing.**

Specifically, as of v0.21.x:

- **No analytics.** No Google Analytics, no Plausible, no PostHog, no
  Amplitude, no Segment, no Mixpanel, no Heap, no Pendo, no FullStory, no
  Hotjar. The frontend bundle has no analytics SDK and no `<script>` tags
  pointing at an analytics provider.
- **No crash reporting.** No Sentry, no Bugsnag, no Rollbar, no Datadog
  RUM, no Honeybadger, no Airbrake. Backend exceptions are logged to
  stderr / journal locally and stay there.
- **No remote logging.** No log shipping to Datadog Logs, Logtail, Loggly,
  Papertrail, or any hosted log aggregator. Application logs go to stderr
  and to the SQLite database on disk; nothing leaves the machine.
- **No usage pings, heartbeats, or "phone home" calls.** Bearings makes
  no outbound HTTP request on startup, on shutdown, on update check, on
  feature use, or on any other trigger. There is no update-check
  subsystem.
- **No CSP violation reporting.** No `report-uri` / `report-to` directives
  pointing at a remote endpoint.
- **No model-call exhaust to anyone but Anthropic.** Bearings drives the
  Claude API via the official `claude-agent-sdk` using your locally
  authenticated credentials. That traffic is between your machine and
  Anthropic, governed by Anthropic's terms — Bearings adds no observer
  in the middle and shares nothing about those calls with anyone else.

All session data — messages, tool outputs, costs, tags, attachments,
checkpoints, templates — stays in `~/.local/share/bearings/` (SQLite
database + uploaded files) on the machine running the server. Backups,
exports, and migrations of that directory are entirely your call.

## The `/metrics` endpoint is local-only

Bearings exposes a [Prometheus](https://prometheus.io/) `/metrics`
endpoint when `metrics.enabled = true` in `~/.config/bearings/config.toml`
(default: `false`). This is **not** outbound telemetry. It is a
read-only endpoint that **a local Prometheus scraper you run** can
poll for operational counters: sessions created, messages persisted,
tool calls started/finished, WebSocket events sent, active connections,
checkpoints, bulk ops, templates. The full collector list is in
[`src/bearings/metrics.py`](src/bearings/metrics.py).

What this means in practice:

- `/metrics` is served on the same loopback bind as the rest of the
  app (`127.0.0.1:8787` by default). Nothing pulls it unless you
  point a scraper at it.
- The counters describe **your** activity on **your** machine. Bearings
  does not aggregate, summarize, ship, or post these numbers anywhere.
- If you don't run a scraper, the counters increment in memory and are
  read by no one. They reset to zero when `bearings serve` restarts.

If you'd rather the endpoint not exist at all, leave `metrics.enabled`
at its default of `false`.

## Versioned acknowledgment

This document is the versioned record of Bearings's data-collection
posture.

> **As of v0.21.x, no opt-in telemetry exists.** Future versions
> documenting opt-in collection will require explicit acknowledgment
> via `bearings telemetry accept --version=X.Y` before any new
> collection takes effect. Operators who do not accept will continue
> to run with the v0.21.x posture (no collection of any kind).

The mechanism above is a **commitment**, not a current implementation:
there is nothing to accept today because there is nothing being
collected. If a future Bearings release introduces any opt-in telemetry
surface, this file will:

1. Bump its version anchor to the release that introduces the surface.
2. Describe the new collection in the same level of detail as the
   "What Bearings collects" section above (categories, vendors, what
   data, what triggers it, where it goes, retention).
3. Document the `bearings telemetry accept --version=X.Y` flow that
   gates the new collection.
4. Default the new surface to **off** unless the operator has
   explicitly accepted the version that introduced it.

No specific telemetry is promised — the commitment is procedural, not
about any particular feature. "We might add opt-in X someday" is the
upper bound; "we won't add anything without acknowledgment" is the
floor.

## Reporting bugs / asking questions

Because nothing is reported automatically, useful bug reports require
operator action. When filing an issue:

- Reproduce locally and copy whatever stderr / journal output, browser
  console output (if you use the devtools), or wire-event payloads
  you're comfortable sharing.
- Redact paths, prompts, tool outputs, and project names before
  pasting. Bearings has no "send anonymized report" button to do that
  for you on purpose — you are the only person who sees your data, so
  you are the one who decides what leaves your machine.

## Related

- [`README.md` § Threat model](README.md#threat-model) — what running
  Bearings exposes on a single-operator workstation, and what each
  permission profile defends against.
- [`docs/checklists.md`](docs/checklists.md) — checklist sessions, the
  primitive that holds long-running work tracked entirely in the
  local SQLite database.
- [`src/bearings/metrics.py`](src/bearings/metrics.py) — every
  Prometheus collector wired into `/metrics`.
