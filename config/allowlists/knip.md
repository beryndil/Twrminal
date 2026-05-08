# Knip baseline allowlist (frontend)

Knip's exception lists live inside `frontend/knip.json`. This file is the
**human-facing** justification log that the auditor reads alongside the
JSON so that every allowlist entry has a recorded reason.

When item 2.x adds or removes an entry from `frontend/knip.json`, the
executor must also append a section here describing **why** the entry is
allowed. The auditor's checklist asks: *"Does every knip allowlist entry
have a justification entry in `config/allowlists/knip.md` dated this
commit?"*

## Schema

```
### <YYYY-MM-DD> · item <#> · <one-line title>

**Field touched:** `ignoreDependencies` | `ignore` | `ignoreBinaries` | `ignoreExportsUsedInFile` | …
**Entries added:** `<entry1>`, `<entry2>`, …
**Justification:** <why these entries are unreferenced from sources but still
required — e.g. "tool invoked via pre-commit, never imported", "Svelte
component-name resolution that knip's static analysis can't follow",
"DevDep used only by CI workflow, not by the build">.
```

---

## Entries

### 2026-04-28 · item 0.1 · Tooling-only devDependencies

**Field touched:** `ignoreDependencies`
**Entries added:** `depcheck`
**Justification:** `depcheck` is invoked exclusively from the pre-commit
configuration and from CI (`npm run depcheck`). It is never imported from
any `.ts` / `.svelte` source, so knip's reachability analysis would
otherwise flag it as unused.

*Note: `ts-prune` was removed from this allowlist entry by finding
feature-12-003 (2026-05-08) — ts-prune was EOL (last published 2021-12-12,
TS 4.x-only) and has been dropped from the gate set entirely. Knip covers
dead-export detection.*
