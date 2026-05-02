/**
 * Frontend sentinel parser — TypeScript mirror of
 * :mod:`bearings.agent.sentinel`.
 *
 * Per ``docs/behavior/checklists.md`` §"Sentinels (auto-pause /
 * failure / completion)" the autonomous driver consumes structured
 * sentinels emitted by the working agent inside its assistant text.
 * Item 1.6 owns the backend parser; this module is the read-side
 * mirror so the ChecklistChat surface can summarise the sentinels in
 * the latest assistant turn for the user.
 *
 * The wire format is the ``<bearings:sentinel kind="…" />`` /
 * open-close XML-ish tag form documented in ``agent/sentinel.py``.
 * Both this and the backend module enforce the same "malformed or
 * incomplete sentinels are ignored" rule (behavior doc verbatim).
 */
import {
  KNOWN_SENTINEL_KINDS,
  SENTINEL_KIND_FOLLOWUP_BLOCKING,
  SENTINEL_KIND_FOLLOWUP_NONBLOCKING,
  SENTINEL_KIND_HANDOFF,
  SENTINEL_KIND_ITEM_BLOCKED,
  SENTINEL_KIND_ITEM_DONE,
  SENTINEL_KIND_ITEM_FAILED,
  ITEM_OUTCOME_BLOCKED,
  KNOWN_ITEM_OUTCOMES,
  type SentinelKind,
} from "./config";

/**
 * One parsed sentinel finding — mirrors
 * :class:`bearings.agent.sentinel.SentinelFinding`. Per-kind payload
 * fields default to ``null``; consumers branch on ``kind`` to know
 * which fields are populated.
 *
 * Not exported: every consumer is internal to this module. The
 * external API surface is :func:`parseSentinels` /
 * :func:`firstTerminalSentinel` — both return arrays of this shape
 * but callers structurally-type against the function's return type.
 * Re-export when a second module imports the type by name (the
 * v1.0 ChecklistChat consumer was removed in the closing-sweep).
 */
interface SentinelFinding {
  kind: SentinelKind;
  plug: string | null;
  label: string | null;
  category: string | null;
  reason: string | null;
}

const TERMINAL_KINDS: ReadonlySet<string> = new Set([
  SENTINEL_KIND_ITEM_DONE,
  SENTINEL_KIND_HANDOFF,
  SENTINEL_KIND_ITEM_BLOCKED,
  SENTINEL_KIND_ITEM_FAILED,
]);

const KNOWN_KINDS: ReadonlySet<string> = new Set<string>(KNOWN_SENTINEL_KINDS);
const KNOWN_OUTCOMES: ReadonlySet<string> = new Set<string>(KNOWN_ITEM_OUTCOMES);

// Self-closing form: <bearings:sentinel kind="item_done" />
const SELF_CLOSING_RE = /<bearings:sentinel\s+kind\s*=\s*"([a-z_]+)"\s*\/>/gi;

// Open/close form: <bearings:sentinel kind="…">…</bearings:sentinel>
// `[\s\S]*?` makes the body span lines without /s flag for older runtimes.
const OPEN_CLOSE_RE =
  /<bearings:sentinel\s+kind\s*=\s*"([a-z_]+)"\s*>([\s\S]*?)<\/bearings:sentinel>/gi;

const PLUG_RE = /<plug>([\s\S]*?)<\/plug>/i;
const LABEL_RE = /<label>([\s\S]*?)<\/label>/i;
const CATEGORY_RE = /<category>([\s\S]*?)<\/category>/i;
const REASON_RE = /<reason>([\s\S]*?)<\/reason>/i;
const TEXT_RE = /<text>([\s\S]*?)<\/text>/i;

/**
 * Parse every sentinel from ``body``, in document order.
 *
 * Per behavior/checklists.md "Malformed or incomplete sentinels are
 * ignored" — an unknown kind, a missing closing tag, or a body whose
 * required inner field is missing is silently dropped. The empty-body
 * case returns an empty array.
 */
export function parseSentinels(body: string): SentinelFinding[] {
  if (body === "") {
    return [];
  }
  const findings: Array<{ start: number; finding: SentinelFinding }> = [];

  for (const match of body.matchAll(SELF_CLOSING_RE)) {
    const kind = match[1].toLowerCase();
    if (!KNOWN_KINDS.has(kind)) continue;
    if (kind !== SENTINEL_KIND_ITEM_DONE) continue;
    findings.push({
      start: match.index ?? 0,
      finding: makeFinding(kind as SentinelKind),
    });
  }

  for (const match of body.matchAll(OPEN_CLOSE_RE)) {
    const kind = match[1].toLowerCase();
    if (!KNOWN_KINDS.has(kind)) continue;
    const finding = buildFinding(kind, match[2]);
    if (finding === null) continue;
    findings.push({ start: match.index ?? 0, finding });
  }

  findings.sort((a, b) => a.start - b.start);
  return findings.map((entry) => entry.finding);
}

/**
 * Pick the first terminal-kind finding (item_done / handoff /
 * item_blocked / item_failed). Followups are non-terminal — they
 * append work but don't close the item per behavior/checklists.md.
 */
export function firstTerminalSentinel(findings: SentinelFinding[]): SentinelFinding | null {
  for (const finding of findings) {
    if (TERMINAL_KINDS.has(finding.kind)) {
      return finding;
    }
  }
  return null;
}

function buildFinding(kind: string, body: string): SentinelFinding | null {
  if (kind === SENTINEL_KIND_ITEM_DONE) {
    return makeFinding(SENTINEL_KIND_ITEM_DONE);
  }
  if (kind === SENTINEL_KIND_HANDOFF) {
    const plug = extractTag(body, PLUG_RE) ?? "";
    return makeFinding(SENTINEL_KIND_HANDOFF, { plug });
  }
  if (kind === SENTINEL_KIND_FOLLOWUP_BLOCKING || kind === SENTINEL_KIND_FOLLOWUP_NONBLOCKING) {
    const label = extractTag(body, LABEL_RE);
    if (label === null || label === "") return null;
    return makeFinding(kind as SentinelKind, { label });
  }
  if (kind === SENTINEL_KIND_ITEM_BLOCKED) {
    const category = extractTag(body, CATEGORY_RE) ?? ITEM_OUTCOME_BLOCKED;
    if (!KNOWN_OUTCOMES.has(category)) return null;
    const text = extractTag(body, TEXT_RE) ?? extractTag(body, REASON_RE);
    return makeFinding(SENTINEL_KIND_ITEM_BLOCKED, { category, reason: text });
  }
  if (kind === SENTINEL_KIND_ITEM_FAILED) {
    const reason = extractTag(body, REASON_RE);
    return makeFinding(SENTINEL_KIND_ITEM_FAILED, { reason });
  }
  return null;
}

function makeFinding(
  kind: SentinelKind,
  overrides: Partial<Omit<SentinelFinding, "kind">> = {},
): SentinelFinding {
  return {
    kind,
    plug: overrides.plug ?? null,
    label: overrides.label ?? null,
    category: overrides.category ?? null,
    reason: overrides.reason ?? null,
  };
}

function extractTag(body: string, pattern: RegExp): string | null {
  const match = pattern.exec(body);
  if (match === null) return null;
  return match[1].trim();
}
