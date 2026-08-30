# SPDX-License-Identifier: GPL-3.0-or-later
"""The cue list, one value at a time: three readers, six writers, and the window between them.

011 spec section 3.5, AC-9, AC-10 and AC-14. Spec section 6 makes converted text a **cue-level**
assertion rather than a byte comparison against the reference - two converters given the same cues
disagree on whitespace and on how they round a timestamp, and no player sees it - so what is
asserted here is that the cues, their text and their timings survive every conversion.

**Two kinds of row live here, and they are not the same kind of claim.** Most assert the cues; a
handful assert *bytes*, and each of those is a place where the obvious document and the
reference's document differ in a way a player can see or a switch can measure: the region a WebVTT
answer declares, the settings on each of its timing lines, the millisecond a zero-length cue is
pushed out by, and the byte order mark five of the six writers begin with.

**No document from the reference's own test data is reproduced here.** The rules those files pin
are cited to the tests that pin them; the documents below are this project's own, written to
exercise the same structures.
"""

from __future__ import annotations

import json

import pytest

from atrium.media.labels import MEDIA_TYPES
from atrium.media.subtitles import (
    BYTE_ORDER_MARK,
    READABLE,
    TICKS_PER_SECOND,
    VTT_TIME_MAP,
    WRITABLE,
    Cue,
    parse,
    render,
    window,
)


def at(seconds: float) -> int:
    """Ticks from seconds, for rows that read better as a clock than as eight digits."""
    return round(seconds * TICKS_PER_SECOND)


#: The list every conversion row below runs on. The second cue is the one spec section 3.5
#: measured the two timestamp switches on - 36.1 s into the file, 6.1 s into a window that starts
#: at 30 s - and the third carries a line break, which is the one piece of text every writer
#: handles differently.
CUES: tuple[Cue, ...] = (
    Cue("1", "The first thing said", at(1.5), at(3.0)),
    Cue("2", "Thirty-six point one", at(36.1), at(38.1)),
    Cue("3", "Two lines\nof it", at(60.0), at(62.5)),
)

#: The four spellings that can be read back, so a round trip is expressible. `json` and `ttml` are
#: written and never read - on this server or on the reference, whose parser table is keyed on
#: subtitle file extensions and holds neither.
ROUND_TRIPPABLE = ("srt", "vtt", "ass", "ssa")


# ------------------------------------------------------------------------------------------
# Reading: the three families
# ------------------------------------------------------------------------------------------

SRT_DOCUMENT = (
    "311\n"
    "00:16:46,465 --> 00:16:49,009\n"
    "The first cue, whose number is not one\n"
    "\n"
    "and which holds a blank line\n"
    "\n"
    "312\n"
    "00:16:49,092 --> 00:16:51,470\n"
    "The second cue\n"
)

VTT_DOCUMENT = (
    "WEBVTT\n"
    "Kind: captions\n"
    "\n"
    "NOTE this line is not a cue and neither is the block it starts\n"
    "\n"
    "a-name-of-its-own\n"
    "00:16:46.465 --> 00:16:49.009 line:90%\n"
    "The first cue\n"
    "\n"
    "16:49.092 --> 16:51.470\n"
    "The second cue, timed without an hours field\n"
)

ASS_DOCUMENT = (
    "[Script Info]\n"
    "Title: something\n"
    "ScriptType: v4.00+\n"
    "\n"
    "[V4+ Styles]\n"
    "Format: Name, Fontname, Fontsize, Encoding\n"
    "Style: Default,Arial,20,1\n"
    "\n"
    "[Events]\n"
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    "Dialogue: 0,0:16:46.46,0:16:49.00,Default,,0000,0000,0000,,"
    "{\\pos(400,570)}The first cue\\Nover two lines\n"
    "Dialogue: 0,0:16:49.09,0:16:51.47,Default,,0000,0000,0000,,The second cue, with a comma\n"
)

SSA_DOCUMENT = (
    "[Script Info]\n"
    "ScriptType: v4.00\n"
    "\n"
    "[Events]\n"
    "Format: Marked, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    "Dialogue: Marked=0,0:16:46.46,0:16:49.00,Default,,0000,0000,0000,,The first cue\n"
)


def test_subrip_keeps_the_numbers_the_file_gave_its_cues() -> None:
    """**The identifier is the file's own number and not the position.** The reference builds it
    from the paragraph's number, and its own parser test pins a document numbered from 311
    answering `"311"` `[source:
    tests/Jellyfin.MediaEncoding.Tests/Subtitles/SrtParserTests.cs:42 @ v10.11.11]`.
    """
    cues = parse(SRT_DOCUMENT, "srt")
    assert [cue.identifier for cue in cues] == ["311", "312"]
    assert cues[0].start_ticks == at(16 * 60 + 46.465)
    assert cues[0].end_ticks == at(16 * 60 + 49.009)


def test_a_subrip_cue_may_hold_a_blank_line() -> None:
    """The row that decides how a cue ends. A blank line does **not** close a SubRip cue - only
    the next number-and-timing pair does - and the reference's parser test pins the same
    `[source: tests/Jellyfin.MediaEncoding.Tests/Subtitles/SrtParserTests.cs:45 @ v10.11.11]`.
    Ending a cue at the first blank line would split this document into four.
    """
    cues = parse(SRT_DOCUMENT, "srt")
    assert len(cues) == 2
    assert cues[0].text == (
        "The first cue, whose number is not one\n\nand which holds a blank line"
    )


def test_webvtt_passes_over_everything_that_is_not_a_cue() -> None:
    """The header block, its metadata line and a `NOTE` block are all skipped, and a cue that
    names itself is still a cue - the name is simply not what the identifier is made of."""
    cues = parse(VTT_DOCUMENT, "vtt")
    assert len(cues) == 2
    assert cues[0].text == "The first cue"


def test_a_webvtt_timestamp_may_omit_its_hours() -> None:
    cues = parse(VTT_DOCUMENT, "vtt")
    assert cues[1].start_ticks == at(16 * 60 + 49.092)


def test_a_webvtt_cue_is_numbered_by_position_whatever_it_calls_itself() -> None:
    """`Cue.identifier` reaches the wire as `Id` on the JSON writer alone, and the reference
    builds it from an integer `[source:
    MediaBrowser.MediaEncoding/Subtitles/SubtitleEditParser.cs:85-89 @ v10.11.11]` - so a WebVTT
    cue's free-text name has nowhere to go. Read rather than measured: no reference test covers
    this family.
    """
    assert [cue.identifier for cue in parse(VTT_DOCUMENT, "vtt")] == ["1", "2"]


def test_substation_reads_its_own_format_line_and_keeps_the_override_tags() -> None:
    """Three things at once, and each of them inverts a plausible shortcut: the column order is
    declared per document rather than fixed, `\\N` is a line break, and a positioning tag is
    **text** - which the reference's own parser test pins `[source:
    tests/Jellyfin.MediaEncoding.Tests/Subtitles/AssParserTests.cs:24 @ v10.11.11]`.
    """
    cues = parse(ASS_DOCUMENT, "ass")
    assert cues[0].text == "{\\pos(400,570)}The first cue\nover two lines"
    assert cues[0].start_ticks == at(16 * 60 + 46.46)


def test_the_last_substation_field_keeps_its_commas() -> None:
    """The text field is last and the delimiter is a comma, so a cue holding one would be cut in
    half by a split that did not stop at the declared column count."""
    assert parse(ASS_DOCUMENT, "ass")[1].text == "The second cue, with a comma"


def test_substation_numbers_its_cues_by_position() -> None:
    """Neither dialect carries a number, and the reference answers `"1"` for the first cue of an
    ASS document `[source: tests/Jellyfin.MediaEncoding.Tests/Subtitles/AssParserTests.cs:21 @
    v10.11.11]`."""
    assert [cue.identifier for cue in parse(ASS_DOCUMENT, "ass")] == ["1", "2"]


def test_the_ssa_dialect_declares_a_different_first_column() -> None:
    """`Marked` where ASS writes `Layer`, and a value of `Marked=0` rather than a number. Reading
    the format line is what makes one reader answer both."""
    assert parse(SSA_DOCUMENT, "ssa")[0].text == "The first cue"


@pytest.mark.parametrize("spelling", READABLE)
def test_every_readable_spelling_reads(spelling: str) -> None:
    """Six spellings, three families. `subrip` and `webvtt` are aliases rather than extensions -
    the reference's parser table is keyed on a **file extension** and holds neither `[source:
    MediaBrowser.MediaEncoding/Subtitles/SubtitleEditParser.cs:100-136 @ v10.11.11]` - so nothing
    can hand them here, and refusing them would be a refusal invented rather than reproduced.
    """
    documents = {
        "srt": SRT_DOCUMENT,
        "subrip": SRT_DOCUMENT,
        "vtt": VTT_DOCUMENT,
        "webvtt": VTT_DOCUMENT,
        "ass": ASS_DOCUMENT,
        "ssa": SSA_DOCUMENT,
    }
    assert parse(documents[spelling], spelling)


def test_a_document_that_yields_no_cues_is_refused_rather_than_answered_empty() -> None:
    """The reference raises on an empty paragraph list `[source:
    MediaBrowser.MediaEncoding/Subtitles/SubtitleEditParser.cs:74-77 @ v10.11.11]`, which is a
    `400` one layer up. A **window** that selects no cues is a different thing entirely and
    answers a body with no cues (spec section 3.7's last row), which is why the refusal lives in
    the reader and not in the writer.
    """
    with pytest.raises(ValueError, match="Unsupported format"):
        parse("this document holds no timings at all\n", "srt")


def test_a_format_outside_the_readable_set_is_refused() -> None:
    with pytest.raises(ValueError, match="Unsupported file extension"):
        parse(SRT_DOCUMENT, "ttml")


# ------------------------------------------------------------------------------------------
# The window: prefix operations, and the switch that decides whose clock it is
# ------------------------------------------------------------------------------------------


def test_a_window_without_the_copy_switch_rebases_on_the_window() -> None:
    """Spec section 3.5's own example, measured: a cue 36.1 s into the file comes back at 6.1 s in
    a window that starts at 30 s."""
    windowed = window(CUES, start_ticks=at(30), end_ticks=0, copy_timestamps=False)
    assert windowed[0].start_ticks == at(6.1)
    assert windowed[0].end_ticks == at(8.1)


def test_a_window_with_the_copy_switch_keeps_the_time_the_cue_has_in_the_file() -> None:
    windowed = window(CUES, start_ticks=at(30), end_ticks=0, copy_timestamps=True)
    assert windowed[0].start_ticks == at(36.1)
    assert windowed[0].text == "Thirty-six point one"


def test_an_end_before_the_start_answers_no_cues() -> None:
    """Spec section 3.7's last row. It is not a special case: the take stops on its first
    candidate, because every cue that survived the skip starts at or after the start position."""
    assert window(CUES, start_ticks=at(30), end_ticks=at(10), copy_timestamps=False) == ()


def test_the_skip_is_a_prefix_and_not_a_filter() -> None:
    """**The row that says why this is written the reference's way** `[source:
    MediaBrowser.MediaEncoding/Subtitles/SubtitleEncoder.cs:100-122 @ v10.11.11]`. The skip stops
    at the first cue that is not before the window, and everything after it is kept - including a
    cue that *is* before the window. A predicate would have dropped the middle one, and a real
    file with overlapping cues is where the two answers part.
    """
    overlapping = (
        Cue("1", "before", at(0), at(5)),
        Cue("2", "inside", at(36.1), at(38.1)),
        Cue("3", "before, but after the first survivor", at(1), at(4)),
    )
    kept = window(overlapping, start_ticks=at(30), end_ticks=0, copy_timestamps=True)
    assert [cue.identifier for cue in kept] == ["2", "3"]


def test_the_take_is_a_prefix_and_not_a_filter() -> None:
    """The same shape at the other end: the take stops at the first cue past the window, and a
    later cue inside it is gone even though its own start qualifies."""
    out_of_order = (
        Cue("1", "inside", at(10), at(12)),
        Cue("2", "past the end", at(80), at(82)),
        Cue("3", "inside, but after the first that was not", at(20), at(22)),
    )
    kept = window(out_of_order, start_ticks=0, end_ticks=at(30), copy_timestamps=True)
    assert [cue.identifier for cue in kept] == ["1"]


def test_an_end_of_zero_is_no_end_at_all() -> None:
    """`endTimeTicks > 0` is the reference's own guard, so a window stating no end keeps every
    cue from the start position onwards rather than none."""
    kept = window(CUES, start_ticks=0, end_ticks=0, copy_timestamps=True)
    assert len(kept) == len(CUES)


def windows_of(cues: tuple[Cue, ...], *, length: int, count: int) -> list[Cue]:
    """The grid the playlist route lays down, concatenated: window *n* is `[n·L, (n+1)·L]`, with
    both bounds passed exactly and consecutive windows **sharing their boundary tick** `[source:
    Jellyfin.Api/Controllers/SubtitleController.cs:380-406 @ v10.11.11]`.
    """
    collected: list[Cue] = []
    for number in range(count):
        collected.extend(
            window(
                cues,
                start_ticks=number * length,
                end_ticks=(number + 1) * length,
                copy_timestamps=True,
            )
        )
    return collected


def test_the_windows_of_a_track_concatenate_back_to_the_track() -> None:
    """AC-10's second half, at the level the cues live on: every cue of the file appears in a
    window of a grid that covers it, once, and in file order - as long as none of them starts on
    a boundary. The row below is the one that says why that clause is there."""
    assert windows_of(CUES, length=at(25), count=3) == list(CUES)


def test_a_cue_that_starts_on_a_window_boundary_is_answered_by_two_windows() -> None:
    """**AC-10's "the concatenation of every window is the whole track" is false of one cue, and
    it is false on the reference.** The skip keeps a cue whose start equals the window's start and
    the take keeps a cue whose start equals its end `[source:
    MediaBrowser.MediaEncoding/Subtitles/SubtitleEncoder.cs:100-112 @ v10.11.11]`, while the
    playlist hands consecutive windows the **same** boundary tick - `EndPositionTicks` of one is
    `StartPositionTicks` of the next `[source:
    Jellyfin.Api/Controllers/SubtitleController.cs:394-405 @ v10.11.11]`. So a cue starting
    exactly on a multiple of the window length is delivered twice, with the file's own timings
    both times, because the playlist sets the copy switch.

    **Read here first and then measured on the reference**, both ways round: a cue at 37.802 s
    answered by the window ending there and by the one starting there, and a cue at 3 282 s
    present in both of the two entries the reference's own playlist writes for that position when
    they are followed as written
    `[probe: tools/probe_subtitle_delivery.py, Jellyfin 10.11.11, 2026-08-30]`.

    A cue merely *straddling* a boundary is not: the next window's skip drops it for ending
    before its start. Only the exact hit is in both.
    """
    boundary = at(30)
    collected = windows_of(CUES, length=boundary, count=3)
    assert [cue.identifier for cue in collected] == ["1", "2", "3", "3"]
    assert CUES[2].start_ticks == boundary * 2, "cue 3 is the one that lands on a boundary"

    straddling = (Cue("1", "across the line", boundary - at(1), boundary + at(1)),)
    assert [cue.identifier for cue in windows_of(straddling, length=boundary, count=2)] == ["1"]


# ------------------------------------------------------------------------------------------
# Writing: the bytes, and what re-reading them gives back
# ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("spelling", ROUND_TRIPPABLE)
def test_every_readable_writer_round_trips_the_cues_and_their_timings(spelling: str) -> None:
    """AC-9's property, asserted per format: the cues, their text and their timings are the
    source's. The **identifier** is not part of it - see the row below."""
    written = render(CUES, spelling).decode("utf-8-sig")
    assert [(cue.text, cue.start_ticks, cue.end_ticks) for cue in parse(written, spelling)] == [
        (cue.text, cue.start_ticks, cue.end_ticks) for cue in CUES
    ]


def test_subrip_renumbers_from_one_and_discards_the_identifier() -> None:
    """**The one place "re-parsed back to the same cues" is false, and it is false on the
    reference too** `[source: MediaBrowser.MediaEncoding/Subtitles/SrtWriter.cs:32 @ v10.11.11]`:
    the writer numbers by position. A track numbered from 311 comes back numbered from 1, which
    is why the round trip above compares text and timings and this row compares the rest.

    Read at 011 T5 and **measured at T7**, which is the only way to see it from outside: a window
    starting past the first cue comes back numbered from `1` under the spelling that renders,
    where the same window's cue-list answer calls that cue `131`
    `[probe: tools/probe_subtitle_delivery.py, Jellyfin 10.11.11, 2026-08-30]`.
    """
    numbered = parse(SRT_DOCUMENT, "srt")
    assert [cue.identifier for cue in numbered] == ["311", "312"]
    written = render(numbered, "srt").decode("utf-8-sig")
    assert [cue.identifier for cue in parse(written, "srt")] == ["1", "2"]


def test_only_the_json_writer_answers_the_identifier_at_all() -> None:
    """Four properties, the reference's own casing, and the cue's own number `[source:
    MediaBrowser.MediaEncoding/Subtitles/JsonWriter.cs:19-38 @ v10.11.11]`."""
    body = json.loads(render(parse(SRT_DOCUMENT, "srt"), "json"))
    assert [event["Id"] for event in body["TrackEvents"]] == ["311", "312"]
    assert body["TrackEvents"][0] == {
        "Id": "311",
        "Text": "The first cue, whose number is not one\n\nand which holds a blank line",
        "StartPositionTicks": at(16 * 60 + 46.465),
        "EndPositionTicks": at(16 * 60 + 49.009),
    }


def test_a_webvtt_answer_declares_a_region_and_places_every_cue_in_it() -> None:
    """**The bytes a naive writer gets wrong, and the one every HLS client sees.** The playlist
    names `stream.vtt` for every window of every track (spec section 3.4), so this writer is the
    whole subtitle path for the video client - and the reference gives it a `Region:` declaration
    and ends every timing line with the settings that place the cue `[source:
    MediaBrowser.MediaEncoding/Subtitles/VttWriter.cs:23-40 @ v10.11.11]`, measured on the wire
    as exactly this header and `00:00:35.099 --> 00:00:37.185 region:subtitle line:90%`
    `[probe: tools/probe_subtitle_delivery.py, Jellyfin 10.11.11, 2026-08-30]`. A `WEBVTT` header
    with bare timing lines parses identically and puts the text somewhere else on the screen.
    """
    lines = render(CUES, "vtt").decode("utf-8-sig").split("\n")
    assert lines[0] == "WEBVTT"
    assert lines[1] == ""
    assert lines[2] == (
        "Region: id:subtitle width:80% lines:3 regionanchor:50%,100% viewportanchor:50%,90%"
    )
    assert lines[3] == ""
    assert lines[4] == "00:00:01.500 --> 00:00:03.000 region:subtitle line:90%"


def test_a_webvtt_cue_that_ends_where_it_starts_is_pushed_out_by_a_millisecond() -> None:
    """The one writer that edits a timing `[source:
    MediaBrowser.MediaEncoding/Subtitles/VttWriter.cs:34-38 @ v10.11.11]`. Written as it is, the
    cue would be zero-length and a player would never show it."""
    written = render((Cue("1", "instant", at(10), at(10)),), "vtt").decode("utf-8-sig")
    assert "00:00:10.000 --> 00:00:10.001 region:subtitle line:90%" in written


def test_the_escaped_line_break_is_handled_in_opposite_directions() -> None:
    """A literal backslash-`n` is a line break that arrived escaped, and the six writers disagree
    about which way it goes: SubRip and WebVTT replace it with a **space**, TTML with `<br/>`, and
    the two SubStation dialects go the other way and turn a real line break into one `[source:
    MediaBrowser.MediaEncoding/Subtitles/SrtWriter.cs:16,41, VttWriter.cs:15,45,
    TtmlWriter.cs:14,44, AssWriter.cs:16,46 @ v10.11.11]`.
    """
    escaped = (Cue("1", "one\\Ntwo", at(1), at(2)),)
    assert "one two" in render(escaped, "srt").decode("utf-8-sig")
    assert "one two" in render(escaped, "vtt").decode("utf-8-sig")
    assert "one<br/>two" in render(escaped, "ttml").decode("utf-8-sig")

    real = (Cue("1", "one\ntwo", at(1), at(2)),)
    assert "Default,one\\ntwo" in render(real, "ass").decode("utf-8-sig")


def test_a_timestamp_is_truncated_and_its_hours_do_not_count_a_day() -> None:
    """Two properties of the platform's own interval formatting, reproduced rather than tidied:
    the fraction is cut and never rounded - so a SubStation answer, which carries hundredths,
    drops the third digit - and the hours field counts what is not part of a day, so a cue 25
    hours in is written `01`.
    """
    late = (Cue("1", "late", at(25 * 3600 + 1.999), at(25 * 3600 + 2)),)
    assert "01:00:01,999 -->" in render(late, "srt").decode("utf-8-sig")
    assert "Dialogue: 0,01:00:01.99," in render(late, "ass").decode("utf-8-sig")


def test_the_ttml_document_is_written_unescaped_and_says_it_is_norwegian() -> None:
    """Both are the reference's `[source:
    MediaBrowser.MediaEncoding/Subtitles/TtmlWriter.cs:26,46-50 @ v10.11.11]`, and both are
    reproduced: the language is hard-coded whatever the track's is, and a cue holding a `<`
    produces a document no XML parser accepts. Correcting either would be a document a client can
    tell from the reference's.
    """
    written = render((Cue("1", "a < b", at(1), at(2)),), "ttml").decode("utf-8-sig")
    assert 'lang="no"' in written
    assert '<p begin="10000000" dur="10000000">a < b</p>' in written


# ------------------------------------------------------------------------------------------
# The byte order mark, and the switch that drops it
# ------------------------------------------------------------------------------------------

#: Five of the six writers go through a text writer that emits the UTF-8 preamble and the JSON
#: writer writes bytes `[source: MediaBrowser.MediaEncoding/Subtitles/SrtWriter.cs:22,
#: JsonWriter.cs:16 @ v10.11.11]`. **`ttml` is one of the five**, which 011 plan section 6.7's
#: list of four omitted.
MARKED = ("srt", "subrip", "vtt", "webvtt", "ass", "ssa", "ttml")


@pytest.mark.parametrize("spelling", WRITABLE)
def test_the_byte_order_mark_is_on_every_writer_but_the_json_one(spelling: str) -> None:
    written = render(CUES, spelling)
    assert written.startswith(BYTE_ORDER_MARK) is (spelling in MARKED)


def test_the_time_map_is_inserted_and_the_byte_order_mark_goes_with_it() -> None:
    """Spec section 3.5, measured: the switch prepends a mapping line **and drops the mark**,
    because the reference rebuilds the finished document to insert it `[source:
    Jellyfin.Api/Controllers/SubtitleController.cs:250-262 @ v10.11.11]`.
    """
    written = render(CUES, "vtt", add_vtt_time_map=True)
    assert not written.startswith(BYTE_ORDER_MARK)
    assert written.decode("utf-8").split("\n")[:2] == ["WEBVTT", VTT_TIME_MAP]


def test_the_time_map_replaces_every_occurrence_and_not_the_leading_one() -> None:
    """**The plan called it a leading replacement and it is a document-wide one.** A cue whose
    text says `WEBVTT` gets a mapping line of its own on the reference, because the rewrite is a
    plain string replacement over the whole answer `[source:
    Jellyfin.Api/Controllers/SubtitleController.cs:259 @ v10.11.11]`.
    """
    talkative = (Cue("1", "the format is called WEBVTT", at(1), at(2)),)
    written = render(talkative, "vtt", add_vtt_time_map=True).decode("utf-8")
    assert written.count(VTT_TIME_MAP) == 2


def test_the_time_map_is_read_against_one_spelling_and_not_its_alias() -> None:
    """`webvtt` reaches the same writer and **not** the same switch: the controller compares the
    requested format with `vtt` alone `[source:
    Jellyfin.Api/Controllers/SubtitleController.cs:250 @ v10.11.11]`. Unreachable in practice -
    `webvtt` has no media type to answer with - and reproduced because the alternative is a
    branch this server has and the reference does not.
    """
    assert render(CUES, "webvtt", add_vtt_time_map=True) == render(CUES, "webvtt")
    assert render(CUES, "vtt", add_vtt_time_map=True) != render(CUES, "vtt")


# ------------------------------------------------------------------------------------------
# The spellings, and determinism
# ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("alias", "canonical"), [("subrip", "srt"), ("webvtt", "vtt"), ("js", "json")]
)
def test_an_alias_answers_what_it_is_an_alias_for(alias: str, canonical: str) -> None:
    """`js` is mapped before anything else, which is the reference's first act on the format it
    was handed `[source: Jellyfin.Api/Controllers/SubtitleController.cs:231-234 @ v10.11.11]`;
    the other two share a writer with the spelling beside them `[source:
    MediaBrowser.MediaEncoding/Subtitles/SubtitleEncoder.cs:275-291 @ v10.11.11]`.
    """
    assert render(CUES, alias) == render(CUES, canonical)


def test_the_format_is_matched_without_regard_to_case() -> None:
    """Every comparison the reference makes on a format is case-insensitive, including the one
    the time map switch is read against."""
    assert render(CUES, "SRT") == render(CUES, "srt")
    assert render(CUES, "VTT", add_vtt_time_map=True) == render(CUES, "vtt", add_vtt_time_map=True)


def test_a_format_outside_the_writable_set_is_refused() -> None:
    with pytest.raises(ValueError, match="Unsupported format"):
        render(CUES, "xyz")


@pytest.mark.parametrize("spelling", WRITABLE)
def test_the_same_cues_render_to_the_same_bytes_twice(spelling: str) -> None:
    """AC-14 at the level it is decidable on: nothing here reads a clock, a locale or a hash
    seed, so a subtitle fetched twice can only differ if something above this module made it."""
    assert render(CUES, spelling) == render(CUES, spelling)


def test_a_window_that_kept_nothing_still_writes_its_header() -> None:
    """Spec section 3.7's *"a body with no cues"* is a document, not an empty body - which is why
    an empty list is a legal argument here and an empty *parse* is not."""
    assert render((), "vtt").decode("utf-8-sig").startswith("WEBVTT")
    assert render((), "srt") == BYTE_ORDER_MARK
    assert render((), "json") == b'{"TrackEvents":[]}'


# ------------------------------------------------------------------------------------------
# The labels beside the cues
# ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("container", "expected"),
    [
        ("ass", "text/x-ssa"),
        ("ssa", "text/x-ssa"),
        ("srt", "application/x-subrip"),
        ("vtt", "text/vtt"),
        ("json", "application/json"),
        ("ttml", "application/ttml+xml"),
    ],
)
def test_every_fetchable_format_has_the_label_the_reference_answers(
    container: str, expected: str
) -> None:
    """`ass` and `ssa` are the reference's own override `[source:
    MediaBrowser.Model/Net/MimeTypes.cs:82-83 @ v10.11.11]`; the other four fall through to a
    third-party table this project cannot cite. **All six are measured**
    `[probe: tools/probe_subtitle_delivery.py, Jellyfin 10.11.11, 2026-08-30]` - `ttml` at 011 T7,
    which is the one spelling that battery had never asked for.
    """
    assert MEDIA_TYPES[container] == expected


@pytest.mark.parametrize("spelling", ["subrip", "webvtt"])
def test_the_two_spellings_with_a_writer_and_no_media_type_have_no_row(spelling: str) -> None:
    """**They are writable, they have no media type, and they are fetched all the same.** The
    reference renders the document and then resolves its label from a lookup on `file.{format}`
    that has no row for either `[source: Jellyfin.Api/Controllers/SubtitleController.cs:261,274,
    MediaBrowser.Model/Net/MimeTypes.cs:158-181 @ v10.11.11]` - and a lookup with no row hands
    back nothing, which the response then *defaults* rather than refusing on. Measured at 011 T7:
    `200` under `application/octet-stream` for both `[probe: tools/probe_subtitle_delivery.py,
    Jellyfin 10.11.11, 2026-08-30]`.

    The rows stay absent, and that is what produces the measured answer rather than contradicting
    it: `media_type_of` returns `None` and `api/subtitles.py` falls through to
    `DEFAULT_MEDIA_TYPE`, which is that same string. Adding a row would be choosing a label where
    the reference chooses none.
    """
    assert spelling in WRITABLE
    assert spelling not in MEDIA_TYPES
