# Tool-output streaming — observable behavior

While the agent is running a tool call (Bash, Edit, Read, web fetch, sub-agent dispatch, etc.), Bearings streams the tool's output into the UI as it arrives rather than waiting for the call to finish. This document lists what the user observes; implementation choices are governed by `docs/architecture-v1.md`.

Sibling subsystems referenced here:
[chat](chat.md), [prompt-endpoint](prompt-endpoint.md).

## When output begins streaming

The user observes streaming only inside a chat conversation pane while a turn is in flight. The sequence:

1. The assistant decides to call a tool. A new row appears inside the **tool-work drawer** (the collapsible `<details>` block above the assistant bubble — see [chat](chat.md)). The row shows the tool name, an elapsed-time readout starting at 00:00, the pretty-printed tool input JSON (muted, above the output area), and an empty output area.
2. As the tool produces stdout / stderr / structured output, the row's output area grows in place. Output appears character-by-character (or chunk-by-chunk for high-bandwidth tools) as it arrives. There is no spinner blocking the output — the elapsed-time readout serves as the live signal.
3. When the tool completes, the row gains a finished marker:
   * **Success.** Green check; final output is preserved as the row's body. The elapsed-time freezes at the final wall-clock duration.
   * **Failure.** Red X; the partial output already streamed remains visible; an error message is appended below it.
4. The drawer's parent assistant bubble continues to grow as the executor's reply streams in around the tool calls.

## When output commits to history

Streamed output is **persisted as it arrives** — the bytes the user saw on screen during the live stream are the same bytes that survive a refresh. Specifically:

* **Per-chunk persistence** is not directly observable, but the consequence is: a tab reload mid-stream re-attaches and the conversation pane redraws with the same partial output already present, plus any newly-arrived chunks since the disconnect (see "Reconnect / replay" below).
* **Commit-on-end.** When a tool call ends, the row's persisted state is finalized: tool name, full input, full output, status (ok / error), start and end timestamps. From that point, navigating away and back redraws the row identically.
* **Pre-commit visibility.** Output that has streamed to the screen but not yet been flushed to durable storage is still visible to the user; a server crash mid-stream may lose the un-flushed tail. The user's recourse is to re-run the turn — there is no per-byte recovery surface.

## Partial-output behavior on tool failure

When a tool call fails:

* **The partial output that already arrived stays visible.** It is not retroactively cleared.
* **The error message is appended** below the partial output, prefixed by a `Error:` annotation in red. The error message is whatever the tool emitted on its failure channel.
* **The row's status pip turns red.**
* **The elapsed-time readout freezes** at the moment of failure.
* **Subsequent tool calls in the same turn proceed normally.** A failure of one tool does not abort the assistant turn unless the agent itself decides to abort.
* **The assistant's reply continues streaming.** The agent typically acknowledges the failure in its next narration block.

The user can right-click the failed row (see [context-menus](context-menus.md)) → Copy tool output / Copy tool input to grab the artifacts for debugging.

## Very-long-output truncation rules

Bearings caps how much output it streams to the screen and persists, to keep a single runaway tool from lagging the UI or filling the database. The user observes:

* **Hard cap on persistence.** A tool that produces output beyond the hard cap has its tail truncated; the row's body ends with a clearly-marked `[truncated — N bytes elided]` annotation. Anything past the hard cap is not recoverable from Bearings; the user must re-run the tool with their own redirect to capture it.
* **Soft-cap inline expander** — *not implemented in v1.0.* The spec describes a two-tier system where a soft cap folds the middle of long output into an inline "Show full output" expander while still persisting the full body. Only the hard-cap tier is implemented; the soft-cap expander will land in a future release.
* **Truncation marker placement.** The marker always appears at the end of the persisted body, never in the middle, so the rendered tail is the actual end of what the tool produced (up to the cap).
* **Long lines.** Long single lines wrap inside the row's body container; horizontal scrolling is not introduced.
* **Multi-byte safety.** The streaming chunks are split on safe boundaries (line breaks, ANSI escape boundaries) so a chunk never splits a multibyte UTF-8 codepoint or an ANSI escape sequence in the middle. The user does not see partial mojibake or stray escape fragments while the stream is live.

## Scroll-anchor behavior

The conversation pane's auto-scroll behaviour is anchored to user intent:

* **At the bottom of the conversation when the turn started.** The pane auto-scrolls to keep the latest content (assistant bubble, tool-work drawer, streaming output) in view. Each new chunk pushes the prior content up; the user always sees the most recent bytes without manual scrolling.
* **Scrolled up by the user.** The pane stops auto-scrolling. New chunks continue to arrive, but the user's reading position is preserved. A small floating affordance ("↓ jump to bottom") appears when there is new content below the viewport. Clicking it both jumps to the bottom and re-engages auto-scroll.
* **Scrolled back to the bottom by the user.** Auto-scroll re-engages automatically — the floating affordance disappears.
* **Tool-work drawer expanded mid-stream.** Expanding the drawer does not re-anchor the scroll — if the user was scrolled up, the drawer expands in place and the viewport stays where it was.
* **A previously-collapsed drawer.** When the drawer was collapsed during streaming and the user later wants to inspect it, the assistant bubble carries a small "⤴ TOOLS" jump button that opens the drawer and scrolls it into view.
* **Conversation pane width changes.** Theme switches and window resizes do not interrupt the streaming output's scroll anchor.

## Reconnect / replay during a stream

If the network drops mid-tool-call (or the user reloads the tab):

1. The conversation pane re-attaches to the live stream when reachable again.
2. Any chunks the agent emitted while the client was away are replayed in order — the user sees the tool row's body fill in retroactively, then live streaming resumes from where it left off.
3. The elapsed-time readout uses the client clock during the live phase and a server-reported timestamp on first replay so a long disconnect doesn't show a wildly inflated client-side timer.
4. Tool calls that completed during the disconnect appear as completed rows during replay, with their final ok / error status and full body.

If the server itself was restarted mid-turn, see [chat](chat.md) — "resuming prompt from previous session" surfaces an inline annotation above the user bubble before the agent re-starts.

## Long-tool keepalive

Some tools produce no output for tens of seconds (sub-agent dispatch, slow web fetch). The user still observes liveness:

* The elapsed-time readout continues to tick — the row never appears frozen.
* Even with no output bytes arriving, a periodic keepalive event keeps the per-tab UI reactive (so a backgrounded tab doesn't render a stale state when refocused mid-call).
* The keepalive is not part of the persisted record. A reconnecting client picks up the live timer from the next live tick rather than replaying keepalives.

## Clickable file paths and URLs in output

File paths and URLs that appear inside tool output are automatically converted to clickable anchors (gap-cycle-06-004):

* **`http(s)://` URLs** become anchors that open in a new tab with `rel="noopener noreferrer"`.
* **Absolute filesystem paths** (e.g. `/home/user/project/src/foo.py`) become `file://` anchors dispatched to the local "Open in editor" handler — no new tab.
* **Workspace-relative paths** (e.g. `src/bearings/agent/runner.py`, `frontend/src/lib/x.svelte`) are resolved against the active session's `working_dir` and rendered as `file://` anchors. Paths that cannot be resolved (no `working_dir` set, or the path would escape the project root via `..`) are left as plain text rather than producing a broken anchor.
* **Explicit `file://` URLs** are treated as file anchors directly.
* **Selecting and copying** a linkified span copies the underlying `href` (the expanded `file://` URL or the full `https://` URL), not the visible text as the tool printed it. This is a known v1.0 limitation — right-clicking and using "Copy tool output" from the context menu gives the full unmodified output text.
* **ANSI escape sequences** are stripped by the HTML sanitizer before rendering. Colored terminal output from tools such as `ls --color` or `git diff` loses its color in the output row. No ANSI-to-color renderer is wired in v1.0.

The same linkification pipeline is used for user message bubbles in the conversation body (see [chat](chat.md) §"Conversation rendering").

## What the user does NOT see

* **Per-byte timestamps.** The streamed output is rendered as bytes, not as a time-stamped log. Per-call start / end times are visible on the row; per-chunk arrival times are not surfaced.
* **ANSI color rendering.** ANSI escape sequences are stripped before display (see §Clickable file paths above). The rendered output shows plain text; colored terminal output appears without color. There is no raw/cooked toggle.
* **Cross-tool aggregation.** The drawer lists each tool call as its own row; there is no merged "all output for this turn" view.
* **Per-chunk ack from the server.** Chunks just appear; there is no progress percentage unless the tool itself emits one in its output.
