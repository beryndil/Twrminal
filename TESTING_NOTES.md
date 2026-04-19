# Testing Notes — Twrminal v0.1.37

Session started: 2026-04-19
Server: http://127.0.0.1:8787 (auth disabled, XDG DB)

## Observations

- **[fixed in v0.1.38]** Prompt send was bound to `⌘/Ctrl+Enter` with
  Enter inserting a newline — reversed now: Enter sends, Shift+Enter
  newlines. Matches chat UI conventions (ChatGPT / Claude / Slack).
  CheatSheet and placeholder updated to match.
- **[fixed in v0.1.38]** Inspector tool-call list was flat — now
  nested under an "Agent" collapsible disclosure with model subtitle
  and a running-count badge; the aside auto-scrolls to the latest
  tool call while the agent is streaming (and the disclosure is
  open).
