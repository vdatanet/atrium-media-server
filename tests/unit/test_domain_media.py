# SPDX-License-Identifier: GPL-3.0-or-later
"""The two numberings, and the one place they meet.

011 spec section 3.6, AC-11 and AC-12. A stream carries two numbers - the wire index a client
sends and a delivery address names, and the demuxer index `-map 0:{n}` is built from - and they
are the same number right up until a subtitle file is discovered beside the media, at which point
every container stream moves by the number of files found.

**The property asserted here is the one `-map` depends on**, and it is deliberately not "the
indices are contiguous": a container stream's wire index exceeds its demuxer index by *exactly*
the number of external streams. Contiguity is true of every list this project builds and would go
on being true if `renumber` numbered the container from zero and the externals after it - which is
the wrong answer, measured `[probe: tools/probe_sidecar_subtitles.py, Jellyfin 10.11.11,
2026-08-29]`, and the one a client would follow into somebody else's audio track.
"""

from __future__ import annotations

from atrium.domain.media import UNSTATED_FILE_INDEX, InspectedStream, StreamKind, renumber

CONTAINER_KINDS = (StreamKind.VIDEO, StreamKind.AUDIO, StreamKind.AUDIO, StreamKind.SUBTITLE)


def container(*, count: int = 4) -> tuple[InspectedStream, ...]:
    """A film's own streams, straight out of an inspection: nothing has renumbered them yet."""
    return tuple(
        InspectedStream(index=n, kind=CONTAINER_KINDS[n % len(CONTAINER_KINDS)])
        for n in range(count)
    )


def sidecars(*paths: str) -> tuple[InspectedStream, ...]:
    """Discovered subtitle files, each the only stream of its own file."""
    return tuple(
        InspectedStream(
            index=0,
            kind=StreamKind.SUBTITLE,
            file_index=0,
            external_path=path,
            codec="subrip",
            is_external=True,
        )
        for path in paths
    )


def the_invariant(streams: tuple[InspectedStream, ...], external_count: int) -> None:
    """Every container stream's wire index exceeds its demuxer index by exactly the file count."""
    own = [one for one in streams if one.external_path is None]
    assert own, "a source with no container streams proves nothing"
    for one in own:
        assert one.index - one.file_index == external_count, (
            f"{one.kind.value} stream at demuxer index {one.file_index} answers wire index "
            f"{one.index}, which is off by {one.index - one.file_index - external_count} - "
            f"a delivery address built from it names a different stream"
        )


# ------------------------------------------------------------------------------------------
# The unstated demuxer index
# ------------------------------------------------------------------------------------------


def test_an_unstated_demuxer_index_reads_back_as_the_wire_index() -> None:
    """Before anything renumbers, the two are one number, and a stream that says nothing about
    its demuxer index is saying that."""
    stream = InspectedStream(index=3, kind=StreamKind.AUDIO)
    assert stream.file_index == 3


def test_a_stated_demuxer_index_is_kept() -> None:
    stream = InspectedStream(index=7, kind=StreamKind.SUBTITLE, file_index=2)
    assert (stream.index, stream.file_index) == (7, 2)


def test_the_sentinel_never_survives_construction() -> None:
    """A caller that reads `file_index` reads a number somebody meant, or the mirror. It never
    reads the sentinel - which is what makes `-map 0:{file_index}` safe to write unguarded."""
    assert UNSTATED_FILE_INDEX < 0
    assert InspectedStream(index=0, kind=StreamKind.VIDEO).file_index == 0


# ------------------------------------------------------------------------------------------
# renumber
# ------------------------------------------------------------------------------------------


def test_a_source_with_no_sidecars_is_numbered_as_it_arrived() -> None:
    streams = renumber(container(), ())
    assert [one.index for one in streams] == [0, 1, 2, 3]
    the_invariant(streams, 0)


def test_the_discovered_files_come_first_and_the_container_moves_by_their_count() -> None:
    """The measured shape: an item whose subtitles are files answers them at 0, 1, 2 and its own
    video and audio begin at 3."""
    streams = renumber(container(), sidecars("film.eng.srt", "film.spa.srt", "film.fre.srt"))
    assert [one.index for one in streams] == [0, 1, 2, 3, 4, 5, 6]
    assert [one.external_path for one in streams[:3]] == [
        "film.eng.srt",
        "film.spa.srt",
        "film.fre.srt",
    ]
    the_invariant(streams, 3)


def test_the_order_given_is_the_order_numbered() -> None:
    """`renumber` sorts nothing. The scan wrote the ordinals in sorted order of `external_path`
    and the repository reads them back by ordinal, so a second sort here could only disagree with
    the numbers already handed to a client."""
    streams = renumber((), sidecars("z.srt", "a.srt"))
    assert [(one.index, one.external_path) for one in streams] == [(0, "z.srt"), (1, "a.srt")]


def test_a_gap_in_the_demuxer_numbering_is_carried_through() -> None:
    """A file whose streams are 0, 1 and 4 - an attachment between them that no inspection kept -
    is the case "the indices are contiguous" would pass and `-map` would fail."""
    own = (
        InspectedStream(index=0, kind=StreamKind.VIDEO, file_index=0),
        InspectedStream(index=1, kind=StreamKind.AUDIO, file_index=1),
        InspectedStream(index=4, kind=StreamKind.SUBTITLE, file_index=4),
    )
    streams = renumber(own, sidecars("film.eng.srt"))
    assert [one.index for one in streams] == [0, 1, 2, 5]
    the_invariant(streams, 1)


def test_the_demuxer_index_is_untouched_by_the_renumbering() -> None:
    """The half that makes the whole arrangement work: what ffmpeg is told never moves."""
    streams = renumber(container(), sidecars("film.eng.srt", "film.spa.srt"))
    own = [one for one in streams if one.external_path is None]
    assert [one.file_index for one in own] == [0, 1, 2, 3]


def test_renumbering_twice_answers_what_renumbering_once_did() -> None:
    """It reads `file_index`, not `index`, so a caller that renumbers an already-numbered list
    gets the same list rather than a doubled offset - which is what a repository that renumbers on
    every read needs to be safe."""
    files = sidecars("film.eng.srt", "film.spa.srt")
    once = renumber(container(), files)
    twice = renumber(
        tuple(one for one in once if one.external_path is None),
        tuple(one for one in once if one.external_path is not None),
    )
    assert once == twice


def test_removing_a_sidecar_puts_every_index_back_where_it_was() -> None:
    """AC-12, as arithmetic rather than as a cleanup path. Nothing stored a wire index, so there
    is nothing to correct: the offset is a function of what the scan found this time."""
    before = renumber(container(), ())
    with_file = renumber(container(), sidecars("film.eng.srt"))
    after = renumber(container(), ())
    assert [one.index for one in with_file if one.external_path is None] == [1, 2, 3, 4]
    assert before == after


def test_a_sidecar_holding_several_streams_keeps_its_own_demuxer_indices() -> None:
    """An `.mks` can carry more than one subtitle. Its streams are numbered by ordinal like any
    other discovered stream, and each keeps the index it has *inside its own file*."""
    files = (
        InspectedStream(
            index=0,
            kind=StreamKind.SUBTITLE,
            file_index=0,
            external_path="film.eng.mks",
            is_external=True,
        ),
        InspectedStream(
            index=0,
            kind=StreamKind.SUBTITLE,
            file_index=1,
            external_path="film.eng.mks",
            is_external=True,
        ),
    )
    streams = renumber(container(), files)
    assert [one.index for one in streams[:2]] == [0, 1]
    assert [one.file_index for one in streams[:2]] == [0, 1]
    the_invariant(streams, 2)
