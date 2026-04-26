#!/usr/bin/env node
// Derives `frontend/package.json` version from the canonical `pyproject.toml`.
//
// Bearings ships as a Python wheel; the frontend bundle is consumed by the
// FastAPI app, not published as a standalone npm package. SemVer requires one
// canonical version per deliverable (~/.claude/coding-standards.md §10), so
// pyproject.toml is the source of truth and this script keeps package.json
// aligned at build time. Runs as the first step of `npm run build` —
// defense-in-depth alongside `tests/test_version_sync.py`, which catches
// drift in CI even before the build runs.

import { readFile, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const pyprojectPath = resolve(here, '..', 'pyproject.toml');
const packagePath = resolve(here, '..', 'frontend', 'package.json');

const pyprojectText = await readFile(pyprojectPath, 'utf8');
// Match the first `version = "..."` under [project]. pyproject.toml has the
// [project] table at the top, so the first match is canonical. A full TOML
// parser would be overkill here and would add a runtime dependency for one
// regex's worth of work.
const versionMatch = pyprojectText.match(/^version\s*=\s*"([^"]+)"/m);
if (!versionMatch) {
    throw new Error(`Could not find version in ${pyprojectPath}`);
}
const canonicalVersion = versionMatch[1];

const packageText = await readFile(packagePath, 'utf8');
const packageJson = JSON.parse(packageText);
const currentVersion = packageJson.version;

if (currentVersion === canonicalVersion) {
    console.log(`frontend version already in sync (${canonicalVersion})`);
} else {
    packageJson.version = canonicalVersion;
    // Preserve the trailing newline + 2-space indent that npm writes.
    await writeFile(packagePath, JSON.stringify(packageJson, null, 2) + '\n');
    console.log(
        `frontend version stamped: ${currentVersion} -> ${canonicalVersion} ` +
            `(from pyproject.toml)`,
    );
}
