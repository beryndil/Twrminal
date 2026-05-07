/**
 * Picker-docs parity contract — asserts that the §"Theme picker UI"
 * option table in ``docs/behavior/themes.md`` matches the live
 * ``KNOWN_THEMES`` alphabet and ``THEME_STRINGS.themeLabels`` defined
 * in ``frontend/src/lib/config.ts``.
 *
 * This is a drift-guard: adding a theme to the alphabet without
 * updating the doc (or vice versa) will fail an assertion here,
 * forcing the committer to update both together.
 *
 * Anchors: ``docs/behavior/themes.md`` §"Theme picker UI"
 * Gap: gap-cycle-14-003
 */
import { readFileSync } from "fs";
import { join } from "path";
import { describe, expect, it } from "vitest";

import { KNOWN_THEMES, THEME_STRINGS } from "../../config";

// process.cwd() in vitest is the frontend/ directory (the one that
// contains vite.config.ts).  The docs live one level up.
const THEMES_DOC = join(process.cwd(), "..", "docs", "behavior", "themes.md");

function readThemesDoc(): string {
  return readFileSync(THEMES_DOC, "utf-8");
}

/**
 * Isolate the text of §"Theme picker UI" (up to the next ## heading).
 */
function pickerSection(doc: string): string {
  const start = doc.indexOf("## Theme picker UI");
  if (start === -1) throw new Error('Section "## Theme picker UI" not found in themes.md');
  const next = doc.indexOf("\n## ", start + 1);
  return next === -1 ? doc.slice(start) : doc.slice(start, next);
}

/**
 * Parse the option rows from the picker table.
 *
 * Each data row has the form:
 *   | `<id>` | "visible label" |
 *
 * Returns an array of ``{ id, label }`` objects in document order.
 * Header and divider rows are skipped automatically because they do
 * not match the backtick-id pattern.
 */
function parsePickerTableRows(doc: string): Array<{ id: string; label: string }> {
  const section = pickerSection(doc);
  const rowRe = /^\|\s+`([^`]+)`\s+\|\s+"([^"]+)"\s+\|/gm;
  const rows: Array<{ id: string; label: string }> = [];
  let m: RegExpExecArray | null;
  while ((m = rowRe.exec(section)) !== null) {
    rows.push({ id: m[1], label: m[2] });
  }
  return rows;
}

// ---------------------------------------------------------------------------
// Option-count and alphabet parity
// ---------------------------------------------------------------------------

describe("picker-docs parity — option count", () => {
  it("the picker table has one row per entry in KNOWN_THEMES", () => {
    const rows = parsePickerTableRows(readThemesDoc());
    expect(rows.length).toBe(KNOWN_THEMES.length);
  });
});

describe("picker-docs parity — every KNOWN_THEMES entry is in the table", () => {
  it("each theme id in KNOWN_THEMES appears as a row in the picker table", () => {
    const rows = parsePickerTableRows(readThemesDoc());
    const docIds = rows.map((r) => r.id);
    for (const theme of KNOWN_THEMES) {
      expect(docIds, `Theme "${theme}" is missing from the picker table in themes.md`).toContain(
        theme,
      );
    }
  });

  it("no extra theme ids appear in the picker table that are absent from KNOWN_THEMES", () => {
    const rows = parsePickerTableRows(readThemesDoc());
    const knownSet = new Set<string>(KNOWN_THEMES);
    for (const { id } of rows) {
      expect(
        knownSet.has(id),
        `Theme "${id}" is in the picker table but not in KNOWN_THEMES`,
      ).toBe(true);
    }
  });
});

// ---------------------------------------------------------------------------
// Label parity
// ---------------------------------------------------------------------------

describe("picker-docs parity — visible labels match THEME_STRINGS.themeLabels", () => {
  it("every row's visible label matches the canonical label from config.ts exactly", () => {
    const rows = parsePickerTableRows(readThemesDoc());
    const labels = THEME_STRINGS.themeLabels as Record<string, string>;
    for (const { id, label } of rows) {
      const expected = labels[id];
      expect(
        label,
        `Label for "${id}" in themes.md ("${label}") does not match THEME_STRINGS.themeLabels ("${expected}")`,
      ).toBe(expected);
    }
  });
});

// ---------------------------------------------------------------------------
// OS-fallback sentence
// ---------------------------------------------------------------------------

describe("picker-docs parity — OS-fallback sentence names correct themes", () => {
  it("the light branch names paper-light as the fallback", () => {
    expect(pickerSection(readThemesDoc())).toContain("`paper-light`");
  });

  it("the dark/non-light branch names evergreen (not midnight-glass) as the fallback", () => {
    const section = pickerSection(readThemesDoc());
    expect(
      section,
      "Dark/non-light OS fallback must be 'evergreen' per resolveOsFallbackTheme()",
    ).toContain("`evergreen` otherwise");
    expect(
      section,
      "themes.md must not say midnight-glass is the dark OS fallback",
    ).not.toContain("`midnight-glass` otherwise");
  });
});
