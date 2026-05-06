# Security policy

## Reporting a vulnerability

Email security reports to **dwhennigan@gmail.com** with the subject prefix `[SECURITY]`. Do **not** open a public GitHub issue for security-sensitive findings until a fix has shipped.

Expected response time: acknowledgement within 72 hours, triage within 7 days. If you don't receive an acknowledgement within 72 hours, please re-send (the email may have been filtered).

## Scope

Bearings is a self-hosted localhost dev tool. Its threat model is bounded accordingly:

- Listens on loopback only by default.
- Single user per install.
- BYO Anthropic credentials (no shared secrets distributed with the app).
- The SQLite database file lives under `$XDG_DATA_HOME/bearings/` and is treated as user-private state.

In-scope reports include: command/SQL injection paths, secrets leaked via logs (despite the `_redact_sensitive` processor), path traversal in the future vault read surface, auth bypass once the shared-token guard lands in §8, and exposure of the Anthropic key.

Out of scope: anything that requires an attacker to already have local code execution as the user running Bearings.

## Mechanical enforcements

- **No secrets in source code (Sec rule 1).** `gitleaks` runs as a pre-commit hook and rejects commits containing AWS keys, GitHub tokens, generic high-entropy strings, etc. Configuration secrets live in env vars (loaded via `pydantic-settings`); the committed `.env.example` is the contract; `.env` is `.gitignore`'d.
- **No PII in logs (Sec rule 2).** `bearings.log` ships a `_redact_sensitive` structlog processor that scrubs values for keys matching a built-in deny-list (`password`, `token`, `authorization`, `cookie`, `api_key`, etc.).
- **Input validation (Sec rule 8).** Inputs crossing a trust boundary are validated through pydantic models before reaching business logic; once the FastAPI surface lands (§8) every request body is a Pydantic model.

## Disclosure timeline

Once a fix is merged and released:

1. A new patch or minor version is tagged.
2. The CHANGELOG records the fix.
3. After a 30-day cooldown, the issue may be discussed publicly.

For high-severity issues, the timeline may be shortened with prior coordination.
