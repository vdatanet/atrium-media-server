# SPDX-License-Identifier: GPL-3.0-or-later
"""The `Range` matrix, as a table - spec section 3.5's rows, in the order they were measured.

Every row here was answered by a real 10.11.11 before it was written down
`[probe: tools/probe_range_matrix.py, Jellyfin 10.11.11, 2026-08-29]`, which is what makes this a
conformance table rather than a restatement of RFC 9110. The two differ in exactly the places that
matter: the reference answers a **reversed** range and every shape of malformed header with the
whole body and a `200`, where the RFC's `416` is what a careful implementation reaches for first.

`tests/conformance/test_static_delivery.py` proves the same rows over HTTP on a real file. This
proves them over the whole space, including the sizes and offsets no fixture has.
"""

from __future__ import annotations

import pytest

from atrium.compat.ranges import (
    FULL_BODY,
    PARTIAL_CONTENT,
    RANGE_NOT_SATISFIABLE,
    negotiate_range,
)

#: The size the measured film had, so the table's arithmetic is the arithmetic that was measured.
SIZE = 3_275_769_255

#: `(header, status, start, length, Content-Range)`. `None` for a header that is absent, and for a
#: `Content-Range` the reference does not send.
MATRIX: tuple[tuple[str | None, int, int, int, str | None], ...] = (
    (None, FULL_BODY, 0, SIZE, None),
    ("bytes=0-99", PARTIAL_CONTENT, 0, 100, f"bytes 0-99/{SIZE}"),
    ("bytes=100-199", PARTIAL_CONTENT, 100, 100, f"bytes 100-199/{SIZE}"),
    ("bytes=0-0", PARTIAL_CONTENT, 0, 1, f"bytes 0-0/{SIZE}"),
    (f"bytes=0-{SIZE - 1}", PARTIAL_CONTENT, 0, SIZE, f"bytes 0-{SIZE - 1}/{SIZE}"),
    ("bytes=100-", PARTIAL_CONTENT, 100, SIZE - 100, f"bytes 100-{SIZE - 1}/{SIZE}"),
    (
        f"bytes={SIZE - 10}-{SIZE + 1000}",
        PARTIAL_CONTENT,
        SIZE - 10,
        10,
        f"bytes {SIZE - 10}-{SIZE - 1}/{SIZE}",
    ),
    ("bytes=-100", PARTIAL_CONTENT, SIZE - 100, 100, f"bytes {SIZE - 100}-{SIZE - 1}/{SIZE}"),
    (f"bytes=-{SIZE + 1000}", PARTIAL_CONTENT, 0, SIZE, f"bytes 0-{SIZE - 1}/{SIZE}"),
    ("bytes=-0", RANGE_NOT_SATISFIABLE, 0, 0, f"bytes */{SIZE}"),
    (f"bytes={SIZE}-", RANGE_NOT_SATISFIABLE, 0, 0, f"bytes */{SIZE}"),
    # The four the reference will not honour, each answered with the entire body.
    ("bytes=0-49,100-149", FULL_BODY, 0, SIZE, None),
    ("bytes=200-100", FULL_BODY, 0, SIZE, None),
    ("bananas", FULL_BODY, 0, SIZE, None),
    ("bytes=", FULL_BODY, 0, SIZE, None),
    ("bytes=-", FULL_BODY, 0, SIZE, None),
    ("bytes=abc-def", FULL_BODY, 0, SIZE, None),
    ("bytes=100-abc", FULL_BODY, 0, SIZE, None),
)


@pytest.mark.parametrize(("header", "status", "start", "length", "content_range"), MATRIX)
def test_the_measured_matrix(
    header: str | None, status: int, start: int, length: int, content_range: str | None
) -> None:
    answer = negotiate_range(header, SIZE)

    assert (answer.status, answer.start, answer.length) == (status, start, length)
    assert answer.content_range == content_range
    assert answer.total == SIZE


def test_a_reversed_range_is_not_a_refusal() -> None:
    """The row most likely to be written the other way round, and the reason this file exists.

    RFC 9110 makes `bytes=200-100` invalid and a careful reader answers `416`. The reference
    answers the whole file with a `200`, so a client that sends a reversed range - which happens,
    from arithmetic that underflowed - keeps playing there and would stop here.
    """
    assert negotiate_range("bytes=200-100", SIZE).status == FULL_BODY
    assert negotiate_range(f"bytes={SIZE}-{SIZE - 100}", SIZE).status == FULL_BODY


def test_naming_the_whole_file_is_still_a_partial_response() -> None:
    """`bytes=0-{size-1}` asks for everything and is answered `206`, not `200` - measured. An
    implementation that collapsed the two would send no `Content-Range` to a client that asked for
    one."""
    answer = negotiate_range(f"bytes=0-{SIZE - 1}", SIZE)

    assert answer.status == PARTIAL_CONTENT
    assert answer.length == SIZE
    assert answer.content_range == f"bytes 0-{SIZE - 1}/{SIZE}"


@pytest.mark.parametrize("header", ["bytes=0-0", "bytes=-1", "bytes=0-"])
def test_a_zero_byte_body_can_satisfy_nothing(header: str) -> None:
    """Not measured and it cannot be: no library file is empty, and a probe has nothing to ask
    with. RFC-consistent, and recorded as the generalisation it is in `compat/ranges.py`."""
    answer = negotiate_range(header, 0)

    assert answer.status == RANGE_NOT_SATISFIABLE
    assert answer.content_range == "bytes */0"


def test_the_unit_is_matched_case_insensitively() -> None:
    """A header field value's token is not case-sensitive, and nothing measured says otherwise -
    so the parser folds rather than pretending to know that the reference does not."""
    assert negotiate_range("BYTES=0-99", SIZE).status == PARTIAL_CONTENT
    assert negotiate_range("  bytes=0-99  ", SIZE).status == PARTIAL_CONTENT


def test_a_small_file_answers_the_same_shapes() -> None:
    """The matrix above runs at the measured film's size; the fixtures are a few hundred kilobytes,
    and a suffix longer than the file is the row where those two disagree if anything does."""
    assert negotiate_range("bytes=-4096", 100).status == PARTIAL_CONTENT
    assert negotiate_range("bytes=-4096", 100).length == 100
    assert negotiate_range("bytes=99-", 100).content_range == "bytes 99-99/100"
    assert negotiate_range("bytes=100-", 100).status == RANGE_NOT_SATISFIABLE
