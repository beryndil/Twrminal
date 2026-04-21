"""Tests pinning the `LineBuffer` invariants.

These are the chunk-boundary gotcha: multibyte UTF-8 codepoints
split across reads must NOT corrupt; ANSI color sequences
terminated before newline must arrive intact as one line.
"""

from __future__ import annotations

from bearings.agent.line_buffer import LineBuffer


def test_yields_complete_lines_only() -> None:
    buf = LineBuffer()
    # Newline-delimited output arrives in arbitrary byte chunks.
    out: list[str] = list(buf.feed(b"line 1\nline 2\n"))
    assert out == ["line 1\n", "line 2\n"]


def test_retains_trailing_partial() -> None:
    buf = LineBuffer()
    assert list(buf.feed(b"line 1\npartial ")) == ["line 1\n"]
    # The second chunk completes the held-over partial line.
    assert list(buf.feed(b"continued\n")) == ["partial continued\n"]


def test_flush_returns_trailing_partial_once() -> None:
    buf = LineBuffer()
    list(buf.feed(b"line 1\nno newline at end"))
    assert buf.flush() == "no newline at end"
    # Second flush after drain returns None.
    assert buf.flush() is None


def test_multibyte_utf8_split_across_feeds_decodes_cleanly() -> None:
    """A 3-byte codepoint (the snowman ☃ = 0xE2 0x98 0x83) split
    across two feeds must round-trip intact. If we decoded per-chunk
    instead of buffering to the newline, the first feed would emit
    mojibake / replacement chars."""
    buf = LineBuffer()
    snowman = "☃".encode()  # b"\xe2\x98\x83"
    assert list(buf.feed(snowman[:2])) == []
    assert list(buf.feed(snowman[2:] + b"\n")) == ["☃\n"]


def test_ansi_escape_sequence_delivered_intact() -> None:
    """Split an ANSI SGR red-foreground sequence across two feeds.
    The line containing it must arrive as a single string — the
    browser's terminal renderer can then parse the escape whole."""
    buf = LineBuffer()
    # ESC[31mRED\x1b[0m\n split mid-sequence.
    assert list(buf.feed(b"\x1b[31mRE")) == []
    yielded = list(buf.feed(b"D\x1b[0m\n"))
    assert yielded == ["\x1b[31mRED\x1b[0m\n"]


def test_replacement_char_on_truly_partial_eof() -> None:
    """If the stream ends mid-codepoint, flush must surface a
    replacement char rather than drop bytes silently."""
    buf = LineBuffer()
    list(buf.feed(b"clean line\n"))
    # Lone lead byte with no continuation.
    list(buf.feed(b"\xe2"))
    tail = buf.flush()
    assert tail is not None
    # Either the replacement char or the question-mark fallback is
    # acceptable; the invariant is "not empty, no exception."
    assert len(tail) > 0


def test_empty_feed_is_noop() -> None:
    buf = LineBuffer()
    assert list(buf.feed(b"")) == []
    assert buf.flush() is None


def test_many_small_chunks() -> None:
    """Stream fed one byte at a time still reconstructs lines."""
    buf = LineBuffer()
    out: list[str] = []
    for byte in b"ab\ncd\n":
        out.extend(buf.feed(bytes([byte])))
    assert out == ["ab\n", "cd\n"]
