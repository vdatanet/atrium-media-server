# SPDX-License-Identifier: GPL-3.0-or-later
"""`Level: 0`, and the two fields that are zero for some stream kinds and absent for others.

008's owes list called these *"values the reference defaults or derives"* and reproducing them *"a
decision and not a wiring fix"*. Reading the source on 2026-09-12 says they are not defaults
anybody chose and there is no decision in them: the reference's probing DTO holds `Level`, `Width`
and `Height` as **non-nullable `int`**, and an absent JSON property deserialising into an `int` is
`0`.

What makes it worth a test file rather than a line is **where** the assignments sit, because that
is what decides which kinds get a zero and which get nothing:

    Level           the common MediaStream initialiser, before any branch   -> every kind
    Width/Height    the subtitle branch and the video branch only           -> those two only

`[source: MediaBrowser.MediaEncoding/Probing/ProbeResultNormalizer.cs:709, 776-777, 823-824 and
MediaStreamInfo.cs:95, 109, 172 @ v10.11.11]`

The distinction is not academic. An audio stream carries **no** `Width` at all, and the reading of
2026-09-10 got this wrong in the one way a probe can: it tested whether the key was *present* and
could not tell `null` from absent. Re-asked on the wire, audio has neither
`[probe: tools/probe_playback_stream_fields.py, Jellyfin 12.0.0, 2026-09-12]`.
"""

from __future__ import annotations

from typing import Any

import pytest

from atrium.domain.media import StreamKind
from atrium.media.probe import FRAMED_KINDS, _stream

EVERY_KIND = ["video", "audio", "subtitle", "data", "attachment"]


def inspected(kind: str, **fields: Any) -> Any:
    return _stream({"codec_type": kind, "index": 0, **fields})


# -- Level: every kind, because the initialiser runs before every branch -----------------------


@pytest.mark.parametrize("kind", EVERY_KIND)
def test_a_stream_the_tool_states_no_level_for_carries_zero(kind: str) -> None:
    assert inspected(kind).level == 0


@pytest.mark.parametrize("kind", EVERY_KIND)
def test_a_level_the_tool_does_state_is_passed_through(kind: str) -> None:
    assert inspected(kind, level=41).level == 41


def test_the_negative_sentinel_survives_rather_than_becoming_zero() -> None:
    """`-99` is `ffprobe`'s "unknown", and the reference stores the number unexamined.

    Folding it to `0` would answer a level the reference does not, and it is the one value where
    "absent" and "stated" are easy to confuse.
    """
    assert inspected("video", level=-99).level == -99


# -- Width and Height: two kinds get zero, the rest get nothing --------------------------------


@pytest.mark.parametrize("kind", ["video", "subtitle"])
def test_a_framed_kind_with_no_frame_size_carries_zero(kind: str) -> None:
    """A **text** subtitle is the case this shows on a real library: it has no frame and the
    reference answers `0`, where a drawn one answers a real size."""
    one = inspected(kind)
    assert (one.width, one.height) == (0, 0)


@pytest.mark.parametrize("kind", ["audio", "data", "attachment"])
def test_every_other_kind_carries_nothing_at_all(kind: str) -> None:
    """The sharp half, and the one the earlier reading had backwards.

    The audio branch assigns neither, so `Width` is **absent** from an audio stream rather than
    `0`. A probe that tested key presence could not tell the two apart; the wire can.
    """
    one = inspected(kind)
    assert (one.width, one.height) == (None, None)


def test_a_drawn_subtitle_keeps_the_size_it_states() -> None:
    """`PGSSUB` carries a real frame where `SUBRIP` carries zeroes, which is why this is a
    coercion of the absent value and never a constant."""
    one = inspected("subtitle", width=1920, height=1080)
    assert (one.width, one.height) == (1920, 1080)


def test_the_framed_kinds_are_the_two_the_reference_branches_on() -> None:
    """A third added here would be a frame size this server answers and the reference does not."""
    assert set(FRAMED_KINDS) == {StreamKind.VIDEO, StreamKind.SUBTITLE}
