#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Which files beside a media file the reference turns into subtitle streams, what it reads out of
their names, and what it calls the codec of every subtitle stream it has.

specs/011 §3.6, §3.2 and OQ-7. A naming question, and naming questions have been the most
expensive class in this repository - so this probe does not describe the rules, it **reproduces**
them and then checks the reproduction against the library the server already has.

The second battery is a different naming question with the same shape. Four subtitle codecs are
renamed when a file is inspected, and the text/image split and the servable-alone rule are both
written against the renamed spelling - so the battery reports the `Codec`,
`IsTextSubtitleStream` and `SupportsExternalStream` of every subtitle stream it can reach, and
predicts the last two from the first.

For every item whose source carries an external subtitle stream, the probe reads the directory
the media file lives in through `/Environment/DirectoryContents` - the read-only filesystem view
the library-setup screen uses - predicts, for every file in it, whether it becomes a stream of
that item and what language, flags and title it would carry, and compares that prediction with
what the server actually reported. A rule that is wrong shows up as a file the probe expected
and the server did not, or the other way round.

It writes nothing and places no fixture: it measures the library that is there. Two things it
therefore cannot reach, and says so rather than guessing: the item's own internal metadata
directory, which is a second place the reference looks and which no API exposes, and any flag
this library happens not to use.

Usage:
    python3 tools/probe_sidecar_subtitles.py http://your-jellyfin:8096 -u username
"""

from __future__ import annotations

import posixpath
from typing import Any

from _playback import find_subtitled_sources, resolve_subtitled_source
from _probe import Probe, ProbeError, Server, main

#: The extensions the reference admits as an external subtitle
#: `[source: Emby.Naming/Common/NamingOptions.cs:163-174 @ v10.11.11]`. Two of them - `.sub` and
#: `.sup` - are image formats, so a file that matches becomes a stream that can never be served
#: as text.
SUBTITLE_EXTENSIONS = (".ass", ".mks", ".sami", ".smi", ".srt", ".ssa", ".sub", ".sup", ".vtt")

#: The one delimiter, and the three flag vocabularies
#: `[source: Emby.Naming/Common/NamingOptions.cs:297-318 @ v10.11.11]`.
DELIMITERS = (".",)
DEFAULT_FLAGS = ("default",)
FORCED_FLAGS = ("foreign", "forced")
HEARING_IMPAIRED_FLAGS = ("cc", "hi", "sdh")

#: How many items to reproduce the rule over. Every one of them costs one directory listing.
SAMPLE = 8

#: What the inspection tool reports for four subtitle codecs, and what the reference renames each
#: to before anything reads it `[source:
#: MediaBrowser.MediaEncoding/Probing/ProbeResultNormalizer.cs:632-652, 765-768 @ v10.11.11]`.
#: Seeing any *key* of this table on the wire would mean the rename does not happen, or does not
#: happen before the properties below are answered.
RENAMED_SUBTITLE_CODECS = {
    "dvb_subtitle": "DVBSUB",
    "dvb_teletext": "DVBTXT",
    "dvd_subtitle": "DVDSUB",
    "hdmv_pgs_subtitle": "PGSSUB",
}

#: The contiguous run of properties between `Index` and `PixelFormat` in the pinned document, minus
#: `IsExternal` which 008 already emits. Counted rather than assumed: which of them a **bare** read
#: carries decides which a stream model may declare without inventing bytes, and four of them are
#: answers to a negotiation rather than facts about a file.
NEIGHBOURING_PROPERTIES = (
    "Score",
    "DeliveryMethod",
    "DeliveryUrl",
    "IsExternalUrl",
    "IsTextSubtitleStream",
    "SupportsExternalStream",
    "Path",
)


def is_text_format(codec: str) -> bool:
    """Whether a codec spelling names a text subtitle format
    `[source: MediaBrowser.Model/Entities/MediaStream.cs:751-761 @ v10.11.11]`."""
    lowered = codec.lower()
    if "microdvd" in lowered:
        return True
    return not (
        "pgs" in lowered or "dvdsub" in lowered or "dvbsub" in lowered or lowered in ("sup", "sub")
    )


def is_pgs_format(codec: str) -> bool:
    """Whether it names the Blu-ray bitmap format
    `[source: MediaBrowser.Model/Entities/MediaStream.cs:765-771 @ v10.11.11]`."""
    lowered = codec.lower()
    return "pgs" in lowered or lowered == "sup"


def predict_file_facts(stream: dict[str, Any]) -> tuple[bool, bool]:
    """What the two file facts should be, from the codec spelling and nothing else.

    A stream with no codec at all is text only when it came from a file beside the media
    `[source: MediaBrowser.Model/Entities/MediaStream.cs:639-654 @ v10.11.11]`, and everything
    that is not a subtitle answers `false` to both.
    """
    external = bool(stream.get("IsExternal"))
    codec = stream.get("Codec") or ""
    if stream.get("Type") != "Subtitle" or (not codec and not external):
        return False, external
    text = is_text_format(codec)
    return text, external or text or is_pgs_format(codec)


class Cultures:
    """The server's own language table, which is what turns a filename token into a language."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.by_token: dict[str, str] = {}
        for row in rows:
            three = row.get("ThreeLetterISOLanguageName") or ""
            two = row.get("TwoLetterISOLanguageName") or ""
            names = list(row.get("ThreeLetterISOLanguageNames") or [])
            tokens = [row.get("Name") or "", row.get("DisplayName") or "", two, three, *names]
            for token in tokens:
                if token:
                    self.by_token.setdefault(token.lower(), three or two)

    def find(self, token: str) -> str | None:
        return self.by_token.get(token.lower())


def parse_sidecar(filename: str, media_stem: str, cultures: Cultures) -> dict[str, Any] | None:
    """What the reference would make of one file sitting beside one media file.

    Reproduced from the reference's behaviour rather than transliterated from it: the stem has to
    match and be followed by a delimiter or nothing, and the rest is read **right to left**, each
    token claimed by the first vocabulary that recognises it, with whatever is left over becoming
    the stream's title.
    """
    stem, dot, extension = filename.rpartition(".")
    if not dot or ("." + extension.lower()) not in SUBTITLE_EXTENSIONS:
        return None
    if len(stem) < len(media_stem) or stem[: len(media_stem)].lower() != media_stem.lower():
        return None
    extra = stem[len(media_stem) :]
    if extra and extra[0] not in DELIMITERS:
        return None
    parsed: dict[str, Any] = {
        "Codec": extension.lower(),
        "Language": None,
        "IsDefault": False,
        "IsForced": False,
        "IsHearingImpaired": False,
        "Title": None,
    }
    title = ""
    remaining = extra
    while remaining:
        cut = remaining.rfind(".")
        if cut == -1:
            break
        slice_ = remaining[cut:]
        token = slice_[1:]
        if any(flag in token.lower() for flag in DEFAULT_FLAGS):
            parsed["IsDefault"] = True
        elif any(flag in token.lower() for flag in FORCED_FLAGS):
            parsed["IsForced"] = True
        elif cultures.find(token) and parsed["Language"] is None:
            parsed["Language"] = cultures.find(token)
        elif token.lower() in HEARING_IMPAIRED_FLAGS:
            parsed["IsHearingImpaired"] = True
        else:
            title = slice_ + title
        remaining = remaining[:cut]
    parsed["Title"] = title[1:] if len(title) >= 1 else None
    return parsed


def _reproduce(server: Server, probe: Probe, cultures: Cultures, item_id: str) -> tuple[bool, str]:
    """Predict this item's external subtitle streams from its directory, and compare."""
    item = server.get("/Items/" + item_id, userId=server.user_id)
    path = item.get("Path") or ""
    if not path:
        return True, "no path reported, skipped"
    directory = posixpath.dirname(path)
    media_stem = posixpath.basename(path).rsplit(".", 1)[0]
    try:
        listing = server.get_where(
            "/Environment/DirectoryContents",
            {"path": directory, "includeFiles": "true", "includeDirectories": "true"},
        )
    except ProbeError as exc:
        return True, f"directory not readable ({exc}), skipped"

    names = sorted(row["Name"] for row in listing if not row.get("IsFolder"))
    folders = [row["Name"] for row in listing if row.get("IsFolder")]
    predicted = []
    for name in names:
        parsed = parse_sidecar(name, media_stem, cultures)
        if parsed is not None:
            predicted.append((name, parsed))

    source = resolve_subtitled_source(server, item_id)
    actual = [s for s in source.subtitles if s.get("IsExternal")]

    if len(predicted) != len(actual):
        return False, (
            f"{len(predicted)} files predicted against {len(actual)} external streams reported: "
            f"predicted {[n for n, _ in predicted]}, "
            f"reported {[posixpath.basename(s.get('Path') or '?') for s in actual]}"
        )
    mismatches = []
    for (name, parsed), stream in zip(predicted, actual, strict=False):
        reported = posixpath.basename(stream.get("Path") or "")
        if reported != name:
            mismatches.append(f"order: expected {name!r}, got {reported!r}")
            continue
        for field in ("Language", "IsForced", "IsDefault", "IsHearingImpaired", "Title"):
            if field == "IsForced" and stream.get(field) and not parsed[field]:
                # The file's own content can carry the flag too, and the reference keeps either.
                continue
            if parsed[field] != stream.get(field):
                mismatches.append(
                    f"{name}: {field} predicted {parsed[field]!r}, got {stream.get(field)!r}"
                )
    summary = f"{len(actual)} external streams from {len(names)} files" + (
        f", {len(folders)} subdirectories not looked in" if folders else ""
    )
    if mismatches:
        return False, summary + "; " + "; ".join(mismatches[:4])
    return True, summary + "; every field reproduced"


def _codec_spellings(probe: Probe, sources: list[Any]) -> list[bool]:
    """Every subtitle stream this library can reach, by codec, with the two file facts.

    Read off the same listing the naming battery uses, so it costs no extra request. Four things
    are checked and each is a different claim: that no spelling the *inspection tool* uses reaches
    the wire, that both facts reproduce from the spelling alone, that both are answered - as
    `false` - on video and audio streams too, and which of the properties beside them a **bare**
    read carries at all.
    """
    tally: dict[tuple[str, bool, bool, bool], int] = {}
    mismatches = []
    other_kinds: dict[tuple[str, bool, bool], int] = {}
    present: dict[str, int] = dict.fromkeys(NEIGHBOURING_PROPERTIES, 0)
    streams_seen = 0
    for source in sources:
        for stream in source.source.get("MediaStreams") or []:
            streams_seen += 1
            for name in NEIGHBOURING_PROPERTIES:
                present[name] += 1 if name in stream else 0
            codec = stream.get("Codec") or ""
            text = stream.get("IsTextSubtitleStream")
            supports = stream.get("SupportsExternalStream")
            if stream.get("Type") != "Subtitle":
                key = (str(stream.get("Type")), bool(text), bool(supports))
                if "IsTextSubtitleStream" not in stream or "SupportsExternalStream" not in stream:
                    mismatches.append(f"{stream.get('Type')} {codec}: a file fact is absent")
                other_kinds[key] = other_kinds.get(key, 0) + 1
                continue
            external = bool(stream.get("IsExternal"))
            row = (codec, bool(text), bool(supports), external)
            tally[row] = tally.get(row, 0) + 1
            predicted = predict_file_facts(stream)
            if predicted != (bool(text), bool(supports)):
                mismatches.append(
                    f"{codec}: predicted {predicted}, reported {(bool(text), bool(supports))}"
                )

    for row in sorted(tally, key=str):
        codec, text, supports, external = row
        probe.observe(
            f"{codec} x{tally[row]}",
            f"IsTextSubtitleStream={text}, SupportsExternalStream={supports}, "
            f"IsExternal={external}",
        )
    probe.observe(
        "the same two facts on everything that is not a subtitle",
        ", ".join(
            f"{kind} x{count}: {text}/{supports}"
            for (kind, text, supports), count in sorted(other_kinds.items(), key=str)
        )
        or "no other streams",
    )

    probe.observe(
        f"the run between Index and PixelFormat, over {streams_seen} streams",
        ", ".join(f"{name} on {count}" for name, count in present.items()),
    )
    # The two file facts on every stream, the four negotiation answers on none, and the path only
    # where a stream came from a file. That is what makes declaring the other five cost no bytes.
    as_expected = (
        present["IsTextSubtitleStream"] == streams_seen
        and present["SupportsExternalStream"] == streams_seen
        and not any(present[name] for name in ("Score", "DeliveryMethod", "DeliveryUrl"))
        and not present["IsExternalUrl"]
        and present["Path"] == sum(count for (_, _, _, ext), count in tally.items() if ext)
    )

    spellings = {codec.lower() for codec, _, _, _ in tally}
    unrenamed = sorted(spellings & set(RENAMED_SUBTITLE_CODECS))
    images = sorted(codec for codec, text, _, _ in tally if not text)
    probe.observe("image subtitle spellings reached", images or "none in this library")
    if mismatches:
        probe.observe("streams whose facts do not follow from the spelling", mismatches[:4])
    if unrenamed:
        probe.observe("spellings the inspection tool would have used", unrenamed)
    if not images:
        probe.note(
            "no image subtitle stream in this library, so the half of the split that inverts "
            "when the rename is skipped was not exercised. Point the probe at a library holding "
            "a Blu-ray or DVD subtitle track to reach it"
        )
    return [not mismatches, not unrenamed, bool(images), as_expected]


def run(server: Server) -> Probe:
    probe = Probe(
        script="probe_sidecar_subtitles.py",
        question=(
            "Which files beside a media file become subtitle streams, what does the reference "
            "read out of their names, and what does it call a subtitle stream's codec?"
        ),
        document="specs/011-subtitle-delivery/spec.md",
        section="§3.6, §3.2, OQ-7",
        expectation=None,
    )
    cultures = Cultures(server.get("/Localization/Cultures"))
    probe.observe("language tokens the server recognises", len(cultures.by_token))

    subtitled = find_subtitled_sources(server)
    candidates = [c for c in subtitled if c.external]
    if not candidates:
        raise ProbeError(
            "no item in this library carries an external subtitle stream, so the rule has "
            "nothing to be reproduced against. Put an .srt beside a film, rescan, and re-run"
        )
    probe.observe(
        "items with an external subtitle stream", f"{len(candidates)} found, {SAMPLE} sampled"
    )

    checks = []
    for candidate in candidates[:SAMPLE]:
        ok, summary = _reproduce(server, probe, cultures, candidate.item_id)
        probe.observe(candidate.item_id[:8], summary)
        checks.append(ok)

    # Two structural consequences of an external stream that no rule about names states.
    sample = resolve_subtitled_source(server, candidates[0].item_id)
    item = server.get("/Items/" + candidates[0].item_id, userId=server.user_id)
    indices = [
        (s["Index"], s["Type"], bool(s.get("IsExternal"))) for s in sample.source["MediaStreams"]
    ]
    probe.observe("HasSubtitles on an item whose subtitles are all files", item.get("HasSubtitles"))
    probe.observe("stream indices, in the order the source lists them", indices)
    external_first = all(
        external for _, _, external in indices[: len(sample.external)]
    ) and not any(external for _, _, external in indices[len(sample.external) :])
    checks.append(bool(item.get("HasSubtitles")))
    checks.append(external_first)

    codecs = sorted({(s.get("Codec") or "?").lower() for c in candidates for s in c.external})
    probe.observe("codecs reported for the discovered files", codecs)

    # The codec-spelling battery, over every subtitle stream in the library rather than only the
    # discovered ones: the four renames concern container tracks and this is where they show.
    checks += _codec_spellings(probe, subtitled)

    probe.note(
        "the reference looks in one more place than this probe can see: the item's own internal "
        "metadata directory, which is where it puts a subtitle it downloaded or extracted. No "
        "route exposes it, so its contribution to a source's stream list is a bound here"
    )
    probe.note(
        "flags this library does not use are read from the reference rather than measured: "
        f"default is {DEFAULT_FLAGS}, forced is {FORCED_FLAGS} and hearing-impaired is "
        f"{HEARING_IMPAIRED_FLAGS}, all matched between {DELIMITERS[0]!r} delimiters - and 'hi' "
        "collides with Hindi, which the reference resolves in Hindi's favour"
    )

    if all(checks):
        probe.conclude(
            "a sidecar is claimed by stem: the filename without its extension must begin with "
            "the media file's own, and either stop there or continue with a dot. What follows "
            "is read right to left, one dot-delimited token at a time, each claimed by the "
            "first vocabulary that recognises it - default, then forced, then a language, then "
            "hearing-impaired - and everything unclaimed becomes the stream's title. The "
            "discovered streams are then numbered **first**, ahead of the container's own, so "
            "putting a file beside a film renumbers every audio and video stream it has; and "
            "HasSubtitles counts them, which is the half 008 §3.1 recorded as missing. And the "
            "codec a subtitle stream reports is the **renamed** spelling, never the inspection "
            "tool's: PGSSUB and DVDSUB rather than hdmv_pgs_subtitle and dvd_subtitle. Both file "
            "facts follow from that spelling alone, on every subtitle stream in the library, and "
            "both are answered as false on every stream that is not a subtitle - so DVDSUB, "
            "which is neither text nor a Presentation Graphic Stream, is the one subtitle codec "
            "here that cannot be served on its own",
            matches_documentation=None,
        )
    else:
        failed = [i for i, ok in enumerate(checks) if not ok]
        probe.conclude(f"checks {failed} did not hold - see observations", False)
    return probe


if __name__ == "__main__":
    raise SystemExit(main(run, __doc__.splitlines()[0]))
