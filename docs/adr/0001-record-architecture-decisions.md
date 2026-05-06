# 1. Record architecture decisions

Date: 2026-05-05

## Status

Accepted

## Context

We need to record the architectural decisions made on this project.
"Architectural" here is a loose term — any decision that constrains
future work, has trade-offs we don't want to re-litigate, or whose
rationale would be lost if not written down. Examples: pinning a
build backend, choosing a logger library, deciding the type-checker
strictness level, picking a database driver.

Without a record, future contributors (including future-me) re-debate
settled choices because the why is missing. Code comments capture
*how*; ADRs capture *why*.

## Decision

We will use Architecture Decision Records (ADRs), as
[described by Michael Nygard][nygard]. Each ADR is one Markdown file
in `docs/adr/` with the filename pattern
`NNNN-kebab-case-title.md`, where `NNNN` is a zero-padded sequential
integer.

Each ADR has these sections:

- **Title** — heading: `# N. Decision title in present tense`.
- **Date** — ISO 8601 date the decision was made.
- **Status** — one of: `Proposed`, `Accepted`, `Deprecated`,
  `Superseded by [N](NNNN-other.md)`.
- **Context** — the forces at play, the problem we're solving.
- **Decision** — what we decided, in present-tense active voice.
- **Consequences** — what becomes easier and what becomes harder
  because of this decision. Both positive and negative.

A blank template is at `docs/adr/template.md`.

## Consequences

**Positive.**

- Decisions are findable. `git log` + grep over `docs/adr/` gives
  the chronology and rationale.
- New contributors have a single place to learn "why is the project
  shaped this way?"
- Reversing a decision creates a new ADR (`Status: Superseded by
  NNNN`) rather than silently changing course.

**Negative.**

- ADRs add ceremony — a small one (one Markdown file), but not zero.
  We accept the friction because the alternative (decisions vanishing
  into commit messages and Slack scrollback) is worse over a project
  lifetime measured in years.
- Numbering creates merge conflicts when two branches add ADRs in
  parallel. Rebasing renumbers the loser; this is rare enough not to
  matter.

[nygard]: https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions
