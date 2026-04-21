"""Stream-safe chunk buffering for tool output deltas.

Gotcha this solves: a raw byte stream from a subprocess can split a
multibyte UTF-8 codepoint or an ANSI escape sequence across two reads.
Forwarding those partial bytes straight to the WebSocket would send
the browser mojibake (incomplete codepoint) or a broken color run
(ANSI `CSI` prefix in one delta, parameters in the next).

`LineBuffer` accumulates bytes and only releases **complete lines**.
The newline byte `0x0A` cannot appear inside a UTF-8 multibyte
sequence (those bytes all have the high bit set, `>= 0x80`), and
practically every shell tool terminates ANSI escapes before a newline
— so newline-bounded chunks are safe to forward as UTF-8 strings.

On stream close, `flush()` returns any trailing partial line so no
bytes are dropped. The trailing partial is decoded with
`errors="replace"` since the stream ended mid-sequence and we have
nothing better to do than surface a replacement char.
"""

from __future__ import annotations

from collections.abc import Iterator


class LineBuffer:
    """Feed raw bytes, yield complete decoded lines.

    Usage:
        buf = LineBuffer()
        while chunk := await stream.read(4096):
            for line in buf.feed(chunk):
                await emit_delta(line)
        if tail := buf.flush():
            await emit_delta(tail)
    """

    __slots__ = ("_buf",)

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, data: bytes) -> Iterator[str]:
        """Append bytes, yield every newline-terminated line (newline
        included in the yielded string). Retains the trailing
        partial line for the next `feed` or `flush` call."""
        if not data:
            return
        self._buf.extend(data)
        while True:
            nl = self._buf.find(b"\n")
            if nl == -1:
                return
            # Slice inclusive of the newline so the terminal pane
            # renders the break as it arrives.
            line_bytes = bytes(self._buf[: nl + 1])
            del self._buf[: nl + 1]
            # Strict decode is safe here: `\n` cannot appear inside a
            # UTF-8 multibyte sequence, so any codepoints in this
            # slice are complete.
            yield line_bytes.decode("utf-8", errors="replace")

    def flush(self) -> str | None:
        """Return any trailing partial line and clear the buffer.

        Call once at end-of-stream. Uses `errors="replace"` because a
        truly-partial-at-EOF multibyte sequence can't be resolved — we
        surface a replacement char rather than drop bytes.
        """
        if not self._buf:
            return None
        tail = bytes(self._buf)
        self._buf.clear()
        return tail.decode("utf-8", errors="replace")
