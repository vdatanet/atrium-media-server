# SPDX-License-Identifier: GPL-3.0-or-later
"""The cue list: three readers, six writers, and the window filter between them.

011 spec section 3.5. Everything here is a function over values - nothing opens a file, starts a
process or knows what a request is - which is what makes spec section 6's *"asserted cue by cue"*
a table test rather than a server test. Making a track readable is `media/extract.py`; this module
begins once the text is in hand.

## What is asserted, and what is not

Spec section 6 settles it: two converters given the same cue list agree on the cues and disagree on
whitespace, on the ordering of optional attributes and on how they round a timestamp. So the
property reproduced here is *the cues, their text and their timings are the source's* - and the
places where a byte comparison against the reference would fail anyway are named below rather than
chased.

## The five things a naive writer gets wrong

Every one of these was read off the reference's own writers, and none of them is guessable from
the format specifications. Three of the five - the region, the placement setting and the mark -
were then measured on a running server, which is what turned the first of them from a plausible
detail into the reason this module renders a header at all:

* **A WebVTT answer carries a region.** The reference writes `WEBVTT`, a blank line, a `Region:`
  declaration, a blank line - and then ends *every* cue's timing line with
  `region:subtitle line:90%` `[source: MediaBrowser.MediaEncoding/Subtitles/VttWriter.cs:23-40 @
  v10.11.11]` - measured on the wire as `00:00:35.099 --> 00:00:37.185 region:subtitle line:90%`
  under that header `[probe: tools/probe_subtitle_delivery.py, Jellyfin 10.11.11, 2026-08-30]`.
  The manifest names `stream.vtt` for every window of every track (spec section 3.4),
  so this is the writer every subtitle a client reaches through the HLS path goes through, and
  cue placement is what the two lines decide. A `WEBVTT\\n\\n` header with bare timing lines is
  well-formed, parses identically and puts the text somewhere else on the screen.
* **A WebVTT cue whose end does not follow its start is pushed out by one millisecond**, rather
  than written as it is `[source: MediaBrowser.MediaEncoding/Subtitles/VttWriter.cs:34-38 @
  v10.11.11]`. It is the one writer that edits a timing.
* **SubRip renumbers from 1** and discards the identifier the cue arrived with `[source:
  MediaBrowser.MediaEncoding/Subtitles/SrtWriter.cs:32 @ v10.11.11]`. Only the JSON writer
  answers `Cue.identifier` at all.
* **`\\n` in the text is a two-character escape, and it is handled in opposite directions.** SubRip
  and WebVTT replace a literal backslash-`n` with a **space**, TTML with `<br/>`, and both are
  case-insensitive; ASS and SSA go the other way, replacing a real line break with a literal
  backslash-`n` `[source: MediaBrowser.MediaEncoding/Subtitles/SrtWriter.cs:16,41,
  VttWriter.cs:15,45, TtmlWriter.cs:14,44, AssWriter.cs:16,46, SsaWriter.cs:16,46 @ v10.11.11]`.
* **Five of the six writers begin with a byte order mark and one does not.** The five write
  through a text writer that emits the UTF-8 preamble; the JSON writer writes bytes directly
  `[source: MediaBrowser.MediaEncoding/Subtitles/SrtWriter.cs:22,
  JsonWriter.cs:16 @ v10.11.11]`. **`ttml` is one of the five** - plan section 6.7 step 4 names
  four - and the mark is measurable from outside, because dropping it is the only thing the time
  map switch does to the header (spec section 3.5). Measured on `vtt`, `ass` and `ssa`, and its
  absence measured on `json` and `js`
  `[probe: tools/probe_subtitle_delivery.py, Jellyfin 10.11.11, 2026-08-30]`; `ttml` is the one
  spelling that battery has never asked for.

## The time map, and why it is a replacement rather than a prefix

`AddVttTimeMap` is not a writer option: the reference renders the whole answer, reads it back as
text - which is where the byte order mark goes, consumed by the reader that detects it - replaces
**every** occurrence of `WEBVTT` in it, and re-encodes `[source:
Jellyfin.Api/Controllers/SubtitleController.cs:250-262 @ v10.11.11]`. Two consequences, both
reproduced here: a cue whose text contains `WEBVTT` gets a time map line of its own, and the
switch is read against the spelling `vtt` alone, so `Stream.webvtt?AddVttTimeMap=true` answers a
plain document with its mark intact.

## Timestamps are truncated components, and the hours wrap at 24

Every writer formats a tick count through the platform's own interval formatter with a fixed
component string - `hh:mm:ss,fff` for SubRip, `hh:mm:ss.fff` for WebVTT, `hh:mm:ss.cc` for ASS
and SSA - which truncates rather than rounds, prints no sign, and counts **hours that are not
part of a day**: a cue 25 hours in is written `01:00:00`. Reproduced as written. No library file
this project will meet is a day long, and inventing a wider field would be a wider field than the
reference has.

## What is read here rather than measured

* **`Cue.identifier` is a number in string form on every path**, because the reference builds it
  from a paragraph's `Number` `[source:
  MediaBrowser.MediaEncoding/Subtitles/SubtitleEditParser.cs:85-89 @ v10.11.11]`. Its own parser
  tests pin both halves of that: a SubRip file numbered from 311 answers `"311"`, and an ASS file,
  which carries no numbers, answers `"1"` `[source:
  tests/Jellyfin.MediaEncoding.Tests/Subtitles/SrtParserTests.cs:42,
  AssParserTests.cs:21 @ v10.11.11]`. WebVTT has no such test; a WebVTT cue identifier is free
  text and cannot become an integer, so the ordinal is what a cue gets here.
* **A document that parses to no cues at all is refused**, rather than answered as an empty list
  `[source: MediaBrowser.MediaEncoding/Subtitles/SubtitleEditParser.cs:74-77 @ v10.11.11]`. A
  *window* that selects no cues is a different thing and answers a body with no cues, which is
  spec section 3.7's last row.
* **The JSON body escapes fewer characters here than there.** The reference's writer escapes
  every non-ASCII character and the HTML-sensitive ASCII ones - measured, a cue arriving as
  `\\u266A \\u003Ci\\u003E\\u00BFVes a la gente` where this one leaves the angle brackets alone
  `[probe: tools/probe_subtitle_delivery.py, Jellyfin 10.11.11, 2026-08-30]`. Both are the same
  string to a parser, which is the argument spec section 6 already makes.
* **`subrip` and `webvtt` are readable here and are not extensions there.** The reference keys its
  parser table on a **file extension** `[source:
  MediaBrowser.MediaEncoding/Subtitles/SubtitleEditParser.cs:100-136 @ v10.11.11]`, and the
  format handed to it is either a sidecar's extension or one of `srt`, `ass`, `ssa` `[source:
  MediaBrowser.MediaEncoding/Subtitles/SubtitleEncoder.cs:204-217, 458-470 @ v10.11.11]` - so
  neither spelling can arrive. They are accepted as aliases because `WRITABLE` names them and a
  caller that hands one back would otherwise be refused for a reason no reference server has.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Final

#: 100-nanosecond units, the unit every position on the Jellyfin wire is in.
TICKS_PER_SECOND: Final = 10_000_000
TICKS_PER_MINUTE: Final = 60 * TICKS_PER_SECOND
TICKS_PER_HOUR: Final = 60 * TICKS_PER_MINUTE
TICKS_PER_DAY: Final = 24 * TICKS_PER_HOUR
TICKS_PER_MILLISECOND: Final = 10_000

#: The UTF-8 preamble the reference's text writers emit, and the only thing the time map drops.
BYTE_ORDER_MARK: Final = b"\xef\xbb\xbf"

#: The one line `AddVttTimeMap` inserts, verbatim `[source:
#: Jellyfin.Api/Controllers/SubtitleController.cs:259 @ v10.11.11]`.
VTT_TIME_MAP: Final = "X-TIMESTAMP-MAP=MPEGTS:900000,LOCAL:00:00:00.000"

#: What `parse` covers: the three readable families, each under both of its spellings.
READABLE: Final[tuple[str, ...]] = ("srt", "subrip", "vtt", "webvtt", "ass", "ssa")

#: What `render` covers: the reference's six writers under the eight spellings that reach them,
#: plus `js` `[source: MediaBrowser.MediaEncoding/Subtitles/SubtitleEncoder.cs:259-301,
#: Jellyfin.Api/Controllers/SubtitleController.cs:231-234 @ v10.11.11]`.
#:
#: **Two of these cannot be fetched, and it is not this module that refuses them.** `subrip` and
#: `webvtt` have a writer and no media type: the label a fetch answers comes from a table keyed on
#: `file.{format}` that has a row for neither `[source:
#: Jellyfin.Api/Controllers/SubtitleController.cs:261,274,
#: MediaBrowser.Model/Net/MimeTypes.cs:158-181 @ v10.11.11]`, so the reference renders the
#: document and then fails on the label. `media/labels.py` therefore has no row for either, and
#: T7 owes the two spellings a probe row.
WRITABLE: Final[tuple[str, ...]] = (
    "srt",
    "subrip",
    "vtt",
    "webvtt",
    "ass",
    "ssa",
    "json",
    "js",
    "ttml",
)

#: Spelling to the writer or reader that answers it. `js` is mapped before anything else, which
#: is the reference's own first act on the format it was given.
_ALIASES: Final[dict[str, str]] = {"subrip": "srt", "webvtt": "vtt", "js": "json"}

#: A literal backslash followed by `n`, either case - what the reference's writers treat as a line
#: break that arrived escaped. Not a newline: that is `_LINE_BREAK`.
_ESCAPED_BREAK: Final = re.compile(r"\\n", re.IGNORECASE)
_LINE_BREAK: Final = re.compile(r"\n")

#: `[HH:]MM:SS[.,]fff --> [HH:]MM:SS[.,]fff`, with whatever the format allows after it. WebVTT
#: admits the two-component form and cue settings; SubRip carries neither and is not harmed by
#: admitting them.
_TIMING = r"(?:(?P<{p}h>\d+):)?(?P<{p}m>\d{{1,3}}):(?P<{p}s>\d{{1,2}})[.,](?P<{p}f>\d{{1,3}})"
_CUE_TIMING: Final = re.compile(
    r"^\s*" + _TIMING.format(p="a") + r"\s*-->\s*" + _TIMING.format(p="b") + r"(?:\s|$)"
)

#: The blocks a WebVTT document carries that are not cues.
_VTT_BLOCK_KEYWORDS: Final = ("NOTE", "STYLE", "REGION")

#: The header the reference's WebVTT writer emits, and the settings it puts on every cue.
_VTT_REGION: Final = (
    "Region: id:subtitle width:80% lines:3 regionanchor:50%,100% viewportanchor:50%,90%"
)
_VTT_CUE_SETTINGS: Final = "region:subtitle line:90%"


@dataclass(frozen=True, slots=True)
class Cue:
    """One event of a subtitle track: what it says, when, and what it is called.

    `identifier` is a number in string form on every path a reference server can take (see the
    module docstring), and it reaches the wire through the JSON writer alone - every other writer
    either renumbers it or has nowhere to put it.
    """

    identifier: str
    text: str
    start_ticks: int
    end_ticks: int


def parse(text: str, source_format: str) -> tuple[Cue, ...]:
    """The cues of one document, in the order it carries them.

    Raises `ValueError` for a format outside `READABLE`, and for a document that yields no cues at
    all - which is the reference's own refusal and not an empty answer.
    """
    canonical = _ALIASES.get(source_format.lower(), source_format.lower())
    readers = {"srt": _read_srt, "vtt": _read_vtt, "ass": _read_ass, "ssa": _read_ass}
    reader = readers.get(canonical)
    if reader is None:
        raise ValueError(f"Unsupported file extension: {source_format}")

    cues = reader(text.removeprefix("\ufeff"))
    if not cues:
        raise ValueError(f"Unsupported format: {source_format}")
    return cues


def window(
    cues: Sequence[Cue], *, start_ticks: int, end_ticks: int, copy_timestamps: bool
) -> tuple[Cue, ...]:
    """The cues of one window, rebased on it unless the timestamps are being copied.

    **Both filters are prefix operations rather than predicates**, which is the reference's own
    shape `[source: MediaBrowser.MediaEncoding/Subtitles/SubtitleEncoder.cs:100-122 @ v10.11.11]`
    and not an accident of how it was written: cues are dropped from the front while *either* end
    of them sits before the start, and then, when an end above zero was given, kept from the front
    while their start is at or before it. A list holding an overlap therefore keeps everything
    after the first match, where a filter would answer a different set - and the row spec section
    3.7 measured, a window whose end precedes its start answering no cues at all, falls out of the
    take stopping on its first candidate.
    """
    kept = list(cues)

    dropped = 0
    for cue in kept:
        if cue.start_ticks - start_ticks < 0 or cue.end_ticks - start_ticks < 0:
            dropped += 1
        else:
            break
    kept = kept[dropped:]

    if end_ticks > 0:
        taken = 0
        for cue in kept:
            if cue.start_ticks <= end_ticks:
                taken += 1
            else:
                break
        kept = kept[:taken]

    if copy_timestamps:
        return tuple(kept)
    return tuple(
        replace(
            cue, start_ticks=cue.start_ticks - start_ticks, end_ticks=cue.end_ticks - start_ticks
        )
        for cue in kept
    )


def render(cues: Sequence[Cue], target_format: str, *, add_vtt_time_map: bool = False) -> bytes:
    """One document, as bytes.

    Bytes and not a string because the byte order mark is part of the answer on five of the six
    writers, and because dropping it is the whole visible effect of the time map switch on the
    header.

    Raises `ValueError` for a format outside `WRITABLE`, which is the reference's refusal before
    any writer is chosen.
    """
    requested = target_format.lower()
    canonical = _ALIASES.get(requested, requested)
    writers = {
        "srt": _write_srt,
        "vtt": _write_vtt,
        "ass": _write_ass,
        "ssa": _write_ssa,
        "json": _write_json,
        "ttml": _write_ttml,
    }
    writer = writers.get(canonical)
    if writer is None:
        raise ValueError(f"Unsupported format: {target_format}")

    document = writer(cues)

    # The switch is read against `vtt` alone and never against its alias, and what it produces is
    # a re-encode of the finished document rather than a different document.
    if add_vtt_time_map and requested == "vtt":
        return document.replace("WEBVTT", f"WEBVTT\n{VTT_TIME_MAP}").encode("utf-8")

    if canonical == "json":
        return document.encode("utf-8")
    return BYTE_ORDER_MARK + document.encode("utf-8")


# ------------------------------------------------------------------------------------------
# Timestamps
# ------------------------------------------------------------------------------------------


def _clock(ticks: int, *, separator: str, digits: int) -> str:
    """A tick count as the platform's fixed-component interval string.

    Truncated, never rounded; unsigned, because a component format string carries no sign; and
    with the hours counted **outside a day**, which is what makes a cue 25 hours in read as one.
    """
    whole = abs(ticks) % TICKS_PER_DAY
    hours, rest = divmod(whole, TICKS_PER_HOUR)
    minutes, rest = divmod(rest, TICKS_PER_MINUTE)
    seconds, rest = divmod(rest, TICKS_PER_SECOND)
    fraction = rest // (TICKS_PER_SECOND // 10**digits)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}{separator}{fraction:0{digits}d}"


def _ticks(hours: str | None, minutes: str, seconds: str, fraction: str) -> int:
    """A parsed timestamp, with the fraction read as a decimal of a second whatever its width."""
    milliseconds = int(fraction.ljust(3, "0")[:3])
    return (
        int(hours or 0) * TICKS_PER_HOUR
        + int(minutes) * TICKS_PER_MINUTE
        + int(seconds) * TICKS_PER_SECOND
        + milliseconds * TICKS_PER_MILLISECOND
    )


def _timing_of(line: str) -> tuple[int, int] | None:
    """The two positions a cue's timing line states, or `None` if it is not one."""
    found = _CUE_TIMING.match(line)
    if found is None:
        return None
    parts = found.groupdict()
    return (
        _ticks(parts["ah"], parts["am"], parts["as"], parts["af"]),
        _ticks(parts["bh"], parts["bm"], parts["bs"], parts["bf"]),
    )


def _lines(text: str) -> list[str]:
    """Line endings normalised, because a subtitle file's are whatever wrote it."""
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def _joined(lines: Sequence[str]) -> str:
    """The text of a cue: its lines, with the blank ones at the end dropped and the ones in the
    middle kept. The reference's own parser tests pin the middle case - a SubRip cue holding a
    blank line keeps it `[source:
    tests/Jellyfin.MediaEncoding.Tests/Subtitles/SrtParserTests.cs:45 @ v10.11.11]`.
    """
    kept = list(lines)
    while kept and not kept[-1].strip():
        kept.pop()
    return "\n".join(kept)


# ------------------------------------------------------------------------------------------
# Readers
# ------------------------------------------------------------------------------------------


def _read_srt(text: str) -> tuple[Cue, ...]:
    """SubRip: a number, a timing line, and text until the next numbered timing line.

    **The end of a cue is not the next blank line**, because a SubRip cue may hold one - so what
    closes a cue is the next number-followed-by-a-timing pair, which is the only structure the
    format has that a body cannot imitate.
    """
    lines = _lines(text)
    headers = [
        (index, timing)
        for index, line in enumerate(lines)
        if (timing := _timing_of(line)) is not None
    ]

    cues: list[Cue] = []
    for ordinal, (header, timing) in enumerate(headers):
        numbered = header > 0 and lines[header - 1].strip().isdigit()
        identifier = lines[header - 1].strip() if numbered else str(ordinal + 1)

        following = headers[ordinal + 1][0] if ordinal + 1 < len(headers) else len(lines)
        if following < len(lines) and lines[following - 1].strip().isdigit():
            following -= 1
        body = _joined(lines[header + 1 : following])

        cues.append(Cue(identifier, body, timing[0], timing[1]))
    return tuple(cues)


def _read_vtt(text: str) -> tuple[Cue, ...]:
    """WebVTT: blank-line-separated blocks, of which the cues are the ones carrying a timing.

    The header block, a `Region:` declaration, a `NOTE` and a `STYLE` all fail that test and are
    passed over - which is also what lets a document this module wrote be read back, region and
    all.
    """
    blocks: list[list[str]] = [[]]
    for line in _lines(text):
        if line.strip():
            blocks[-1].append(line)
        elif blocks[-1]:
            blocks.append([])

    cues: list[Cue] = []
    for block in blocks:
        if not block or block[0].split()[0].upper().startswith(_VTT_BLOCK_KEYWORDS):
            continue
        # The timing line is the first line of a cue, or its second when the document gave the
        # cue a name of its own.
        timed = [
            (index, timing)
            for index, line in enumerate(block[:2])
            if (timing := _timing_of(line)) is not None
        ]
        if not timed:
            continue
        header, timing = timed[0]
        # A cue identifier is free text and the wire wants a number, so the ordinal is what a cue
        # is called here whether or not the document named it.
        cues.append(Cue(str(len(cues) + 1), _joined(block[header + 1 :]), timing[0], timing[1]))
    return tuple(cues)


def _read_ass(text: str) -> tuple[Cue, ...]:
    """ASS and SSA: the `[Events]` section, read through its own `Format:` line.

    The column order is declared per file and the two dialects declare different orders, so the
    header is what says which field is which - and the text field is last, which is why it is the
    one that may hold the delimiter. `\\N` and `\\n` are line breaks and every other override tag
    is text: the reference's own parser test keeps a positioning tag in the answer `[source:
    tests/Jellyfin.MediaEncoding.Tests/Subtitles/AssParserTests.cs:24 @ v10.11.11]`.
    """
    fields: list[str] = []
    in_events = False
    cues: list[Cue] = []

    for line in _lines(text):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_events = stripped.lower() == "[events]"
            continue
        if not in_events:
            continue

        keyword, _, rest = stripped.partition(":")
        keyword = keyword.strip().lower()
        if keyword == "format":
            fields = [name.strip().lower() for name in rest.split(",")]
            continue
        if keyword != "dialogue" or not fields:
            continue

        values = rest.split(",", len(fields) - 1)
        if len(values) < len(fields):
            continue
        row = dict(zip(fields, values, strict=True))
        if "start" not in row or "end" not in row:
            continue
        timing = _timing_of(f"{row['start']} --> {row['end']}")
        if timing is None:
            continue
        body = _ESCAPED_BREAK.sub("\n", row.get("text", ""))
        cues.append(Cue(str(len(cues) + 1), body, timing[0], timing[1]))

    return tuple(cues)


# ------------------------------------------------------------------------------------------
# Writers
# ------------------------------------------------------------------------------------------


def _write_srt(cues: Sequence[Cue]) -> str:
    out: list[str] = []
    for number, cue in enumerate(cues, 1):
        start = _clock(cue.start_ticks, separator=",", digits=3)
        end = _clock(cue.end_ticks, separator=",", digits=3)
        out.append(f"{number}\n{start} --> {end}\n{_ESCAPED_BREAK.sub(' ', cue.text)}\n\n")
    return "".join(out)


def _write_vtt(cues: Sequence[Cue]) -> str:
    out: list[str] = [f"WEBVTT\n\n{_VTT_REGION}\n\n"]
    for cue in cues:
        # The one writer that edits a timing: an end that does not follow its start is pushed out
        # by a millisecond rather than written as it is.
        end_ticks = (
            cue.end_ticks
            if cue.end_ticks > cue.start_ticks
            else cue.start_ticks + TICKS_PER_MILLISECOND
        )
        start = _clock(cue.start_ticks, separator=".", digits=3)
        end = _clock(end_ticks, separator=".", digits=3)
        out.append(
            f"{start} --> {end} {_VTT_CUE_SETTINGS}\n{_ESCAPED_BREAK.sub(' ', cue.text)}\n\n"
        )
    return "".join(out)


def _substation(cues: Sequence[Cue], *, header: str) -> str:
    out: list[str] = [header]
    for cue in cues:
        start = _clock(cue.start_ticks, separator=".", digits=2)
        end = _clock(cue.end_ticks, separator=".", digits=2)
        # A real line break goes back out as the two-character escape the format carries it in.
        body = _LINE_BREAK.sub(r"\\n", cue.text)
        out.append(f"Dialogue: 0,{start},{end},Default,{body}\n")
    return "".join(out)


#: The two headers, verbatim `[source: MediaBrowser.MediaEncoding/Subtitles/AssWriter.cs:28-37,
#: SsaWriter.cs:28-37 @ v10.11.11]`. They differ in the script type, the styles section name, the
#: style's own column list and the title the reference gives itself.
_ASS_HEADER: Final = (
    "[Script Info]\n"
    "Title: Jellyfin transcoded ASS subtitle\n"
    "ScriptType: v4.00+\n"
    "\n"
    "[V4+ Styles]\n"
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
    "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
    "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
    "Style: Default,Arial,20,&H00FFFFFF,&H00FFFFFF,&H19333333,&H910E0807,0,0,0,0,100,100,0,0,"
    "0,1,0,2,10,10,10,1\n"
    "\n"
    "[Events]\n"
    "Format: Layer, Start, End, Style, Text\n"
)
_SSA_HEADER: Final = (
    "[Script Info]\n"
    "Title: Jellyfin transcoded SSA subtitle\n"
    "ScriptType: v4.00\n"
    "\n"
    "[V4 Styles]\n"
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, TertiaryColour, "
    "BackColour, Bold, Italic, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, "
    "MarginV, AlphaLevel, Encoding\n"
    "Style: Default,Arial,20,&H00FFFFFF,&H00FFFFFF,&H19333333,&H19333333,0,0,0,1,0,2,10,10,10,"
    "0,1\n"
    "\n"
    "[Events]\n"
    "Format: Layer, Start, End, Style, Text\n"
)


def _write_ass(cues: Sequence[Cue]) -> str:
    return _substation(cues, header=_ASS_HEADER)


def _write_ssa(cues: Sequence[Cue]) -> str:
    return _substation(cues, header=_SSA_HEADER)


def _write_json(cues: Sequence[Cue]) -> str:
    """The cue list as an object of `TrackEvents`, in the reference's four properties and its own
    casing `[source: MediaBrowser.MediaEncoding/Subtitles/JsonWriter.cs:19-38 @ v10.11.11]`. No
    whitespace and no trailing newline, because the reference writes bytes rather than lines.
    """
    events = [
        {
            "Id": cue.identifier,
            "Text": cue.text,
            "StartPositionTicks": cue.start_ticks,
            "EndPositionTicks": cue.end_ticks,
        }
        for cue in cues
    ]
    return json.dumps({"TrackEvents": events}, separators=(",", ":"))


def _write_ttml(cues: Sequence[Cue]) -> str:
    """TTML, including the two things about it that look like mistakes and are the answer.

    The document declares `lang="no"` on every track whatever the track's language is, and the
    cue text is written **unescaped** - so a cue holding a `<` produces a document no XML parser
    accepts `[source: MediaBrowser.MediaEncoding/Subtitles/TtmlWriter.cs:26,46-50 @ v10.11.11]`.
    Both are reproduced: this is the format no analysed client asks for, it is written because
    the reference writes it (plan section 6.7), and a document that differed would be a document
    a client could tell apart.
    """
    out: list[str] = [
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<tt xmlns="http://www.w3.org/ns/ttml" '
        'xmlns:tts="http://www.w3.org/2006/04/ttaf1#styling" lang="no">\n'
        "<head>\n"
        "<styling>\n"
        '<style id="italic" tts:fontStyle="italic" />\n'
        '<style id="left" tts:textAlign="left" />\n'
        '<style id="center" tts:textAlign="center" />\n'
        '<style id="right" tts:textAlign="right" />\n'
        "</styling>\n"
        "</head>\n"
        "<body>\n"
        "<div>\n"
    ]
    for cue in cues:
        body = _ESCAPED_BREAK.sub("<br/>", cue.text)
        duration = cue.end_ticks - cue.start_ticks
        out.append(f'<p begin="{cue.start_ticks}" dur="{duration}">{body}</p>\n')
    out.append("</div>\n</body>\n</tt>\n")
    return "".join(out)


__all__ = [
    "BYTE_ORDER_MARK",
    "READABLE",
    "TICKS_PER_SECOND",
    "VTT_TIME_MAP",
    "WRITABLE",
    "Cue",
    "parse",
    "render",
    "window",
]
