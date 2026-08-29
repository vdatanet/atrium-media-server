# SPDX-License-Identifier: GPL-3.0-or-later
"""`Range`, resolved against a known size - the whole of spec section 3.5's table, in one place.

Every delivery route in feature 008 whose body has a known size answers ranges, and they must all
answer them identically: a player that seeks does it on `/Videos/{id}/stream` and on an HLS
segment with the same code, and a route that parsed the header slightly differently would be a
route that seeks slightly differently. So the parsing is one function and the routes carry none.

**The table is measured, row by row, not designed**
`[probe: tools/probe_range_matrix.py, Jellyfin 10.11.11, 2026-08-29]`:

| Header | Answer |
|---|---|
| absent | `200`, the whole body |
| `bytes=0-99`, `bytes=100-199`, `bytes=0-0` | `206`, exactly those bytes |
| `bytes=0-{size-1}` | `206` - naming the whole file is still a range, never a `200` |
| `bytes=100-` | `206`, from there to the end |
| `bytes={size-10}-{size+1000}` | `206`, clamped to the last byte |
| `bytes=-100` | `206`, the last hundred |
| `bytes=-{size+1000}` | `206`, the whole file |
| `bytes=-0` | `416` |
| `bytes={size}-` | `416`, `Content-Range: bytes */{size}`, `Content-Length: 0` |
| `bytes=0-49,100-149` | `200`, the whole body - the reference does not split |
| `bytes=200-100` | `200`, the whole body - **not** a `416` |
| `bananas`, `bytes=`, `bytes=-`, `bytes=abc-def`, `bytes=100-abc` | `200`, the whole body |

The last row is the one worth having measured rather than reasoned: five different shapes of
nonsense, and every one of them is a `200` with the entire file. An implementation that answered
`416` to a malformed header - which several do, and which reads as the stricter choice - would
refuse a request the reference serves.

**Two rows are a generalisation of a measured one and say so here.** A reversed range whose start
is also past the end (`bytes={size}-{size-100}`) is treated as the measured reversed case rather
than as the measured past-the-end one, because a reversed range is not a range at all - the
reference's parser discards the header and serves the body, and that reading is what makes one
rule out of two rows. And a range against a **zero-byte** file is unsatisfiable, which no library
file can exercise and no probe could ask.
"""

from __future__ import annotations

from dataclasses import dataclass

#: The only range unit there is, and the only one the reference answers.
BYTES_UNIT = "bytes="

#: What the three answers are, by status. Named so a caller reads `answer.status ==
#: PARTIAL_CONTENT` rather than a number, and so the three cannot be confused with the statuses a
#: delivery route decides for other reasons.
FULL_BODY = 200
PARTIAL_CONTENT = 206
RANGE_NOT_SATISFIABLE = 416


@dataclass(frozen=True, slots=True)
class RangeAnswer:
    """One resolved request for bytes: which of them, and what the response says about it.

    `start` and `length` describe what to send in every case - a refusal sends nothing, and a
    request with no range sends everything - so a caller never branches on the status to know how
    much to read.
    """

    status: int
    start: int
    length: int
    total: int

    @property
    def content_range(self) -> str | None:
        """The header, or `None` where the reference sends none.

        A `416` names the size it could not satisfy and nothing else, which is what tells a client
        the file shrank rather than that its arithmetic is broken.
        """
        if self.status == PARTIAL_CONTENT:
            return f"bytes {self.start}-{self.start + self.length - 1}/{self.total}"
        if self.status == RANGE_NOT_SATISFIABLE:
            return f"bytes */{self.total}"
        return None

    @property
    def is_refusal(self) -> bool:
        return self.status == RANGE_NOT_SATISFIABLE


def negotiate_range(header: str | None, size: int) -> RangeAnswer:
    """Resolve a `Range` header against a body of `size` bytes.

    The whole body is the answer to everything the reference will not or cannot honour, which is
    most of the malformed space: that is the measured behaviour and it is also the forgiving one.
    """
    whole = RangeAnswer(FULL_BODY, 0, size, size)
    unsatisfiable = RangeAnswer(RANGE_NOT_SATISFIABLE, 0, 0, size)

    if not header:
        return whole
    text = header.strip()
    if text[: len(BYTES_UNIT)].lower() != BYTES_UNIT:
        return whole
    spec = text[len(BYTES_UNIT) :].strip()
    if "," in spec:
        # Several ranges. The reference does not build a multipart body, and a client that asked
        # for two slices can read one body instead.
        return whole

    first, separator, last = spec.partition("-")
    if not separator:
        return whole
    first, last = first.strip(), last.strip()

    if not first:
        # The suffix form: the last `n` bytes, and `n` larger than the file is the whole file.
        if not last.isdigit():
            return whole
        wanted = int(last)
        if wanted == 0 or size == 0:
            return unsatisfiable
        start = max(0, size - wanted)
        return RangeAnswer(PARTIAL_CONTENT, start, size - start, size)

    if not first.isdigit():
        return whole
    start = int(first)

    if last:
        if not last.isdigit():
            return whole
        if int(last) < start:
            # Reversed, which the reference reads as no range at all rather than as a refusal -
            # measured on `bytes=200-100`, and applied here to a reversed pair whose start is
            # also past the end.
            return whole
        end = min(int(last), size - 1)
    else:
        end = size - 1

    if start >= size:
        return unsatisfiable
    return RangeAnswer(PARTIAL_CONTENT, start, end - start + 1, size)


__all__ = [
    "BYTES_UNIT",
    "FULL_BODY",
    "PARTIAL_CONTENT",
    "RANGE_NOT_SATISFIABLE",
    "RangeAnswer",
    "negotiate_range",
]
