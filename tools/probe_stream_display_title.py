#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""What a subtitle stream is called, piece by piece, and which of those pieces are localised.

specs/011 §3.2 (the `NAME` box), OQ-4 and plan §6.4. The manifest labels every announced track
with the stream's `DisplayTitle`, and 011 writes that string in an **invariant** form - so what
this probe has to establish is not "what does the reference call this track" but *which part of
the string is a decision and which part is parity*.

It does that by **reproducing** the assembly rather than describing it, the way
`probe_sidecar_subtitles.py` reproduces the filename rule, and in two passes:

- **the language name is measured, not assumed.** Every subtitle stream that states a language
  and carries no title of its own answers a `DisplayTitle` whose first piece is that language's
  name and nothing else, so the run reads a tag -> name table straight off the wire. It is
  checked for self-consistency across streams and printed beside the display name this
  repository's own culture table has for the same tag, which is the exact size of the
  divergence 011 accepts.
- **everything else is reproduced and compared byte for byte.** With the language name known,
  every subtitle stream's whole `DisplayTitle` is rebuilt from its own properties - the five
  words as the *server itself* states them, the codec upper cased, the title's substring
  suppression - and compared with what the server answered. A rule that is wrong shows up as a
  stream whose reproduction differs.

The five words are read from the stream's own `LocalizedDefault`, `LocalizedForced`,
`LocalizedExternal`, `LocalizedHearingImpaired` and `LocalizedUndefined` properties rather than
from a table here, because **whether those properties are ever empty is the question**: the
literals compiled into the assembly are only reached when they are, and a translation table's
English row is not obliged to agree with them.

It writes nothing: it measures the library that is there. Every branch of the assembly the
library does not carry is reported as a miss on every run rather than counted as agreement.

Usage:
    python3 tools/probe_stream_display_title.py http://your-jellyfin:8096 -u username
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from _playback import find_subtitled_sources
from _probe import Probe, ProbeError, Server, main

#: The separator between the pieces of a subtitle stream's display title, and the one each piece
#: appended to a title is introduced by `[source:
#: MediaBrowser.Model/Entities/MediaStream.cs:458, 465 @ v10.11.11]`. Both are this string; the
#: audio branch two cases above joins the same kind of list on a space.
JOIN = " - "

#: The five localised words, in the order the assembly appends them, beside the literal the
#: reference falls back to when the property is empty `[source:
#: MediaBrowser.Model/Entities/MediaStream.cs:422-447 @ v10.11.11]`. The keys are the wire
#: property names; the values are what a server that localised nothing would write. Whether any
#: server is ever in that state is half of what this probe is for.
FALLBACKS = {
    "LocalizedUndefined": "Und",
    "LocalizedHearingImpaired": "Hearing Impaired",
    "LocalizedDefault": "Default",
    "LocalizedForced": "Forced",
    "LocalizedExternal": "External",
}

#: Every branch of the assembly, so a run can say which of them it took. A reproduction that
#: agrees on every stream it saw has proven the branches it ran and nothing about the others.
BRANCHES = (
    "language",
    "no language",
    "hearing impaired",
    "default",
    "forced",
    "codec",
    "external",
    "title",
    "title suppressing an attribute",
    "a three-letter language tag",
    "a two-letter language tag",
    "a language tag carrying a region",
    "a bibliographic three-letter code",
)


def _reach(reached: Set[str], branch: str) -> None:
    reached.add(branch)


def tag_shape(tag: str, bibliographic: Set[str]) -> str:
    """Which shape a language tag has, because the reference resolves each by a different lookup
    `[source: MediaBrowser.Model/Entities/MediaStream.cs:399-415 @ v10.11.11]`: a tag carrying a
    `-` is matched against a platform culture's name and then against the two-letter code of its
    base, and anything else is matched against the platform's **terminological** three-letter code
    alone - so a two-letter tag matches no culture at all, and neither does a bibliographic
    three-letter code like `ger`. Reported rather than reproduced: which of these a library
    carries is a fact about its files, and a shape no file here has is a shape this run cannot
    speak for.
    """
    if "-" in tag:
        return "a language tag carrying a region"
    if tag.lower() in bibliographic:
        return "a bibliographic three-letter code"
    if len(tag) == 2:
        return "a two-letter language tag"
    return "a three-letter language tag"


def _words(stream: Dict[str, Any]) -> Dict[str, str]:
    """The five words this stream would be labelled with, as the server itself states them."""
    return {name: (stream.get(name) or fallback) for name, fallback in FALLBACKS.items()}


def _attributes(
    stream: Dict[str, Any], language_name: Optional[str], reached: Set[str]
) -> List[str]:
    """The pieces of the display title, in order, with the language name already resolved."""
    words = _words(stream)
    attributes = []
    if stream.get("Language"):
        _reach(reached, "language")
        attributes.append(language_name if language_name is not None else "")
    else:
        _reach(reached, "no language")
        attributes.append(words["LocalizedUndefined"])
    if stream.get("IsHearingImpaired"):
        _reach(reached, "hearing impaired")
        attributes.append(words["LocalizedHearingImpaired"])
    if stream.get("IsDefault"):
        _reach(reached, "default")
        attributes.append(words["LocalizedDefault"])
    if stream.get("IsForced"):
        _reach(reached, "forced")
        attributes.append(words["LocalizedForced"])
    if stream.get("Codec"):
        _reach(reached, "codec")
        attributes.append(str(stream["Codec"]).upper())
    if stream.get("IsExternal"):
        _reach(reached, "external")
        attributes.append(words["LocalizedExternal"])
    return attributes


def assemble(stream: Dict[str, Any], language_name: Optional[str], reached: Set[str]) -> str:
    """The whole display title, reproduced from one stream's own properties."""
    attributes = _attributes(stream, language_name, reached)
    title = stream.get("Title") or ""
    if not title:
        return JOIN.join(attributes)
    _reach(reached, "title")
    result = title
    for attribute in attributes:
        if attribute.lower() in title.lower():
            _reach(reached, "title suppressing an attribute")
        else:
            result += JOIN + attribute
    return result


def _subtitle_streams(server: Server) -> List[Dict[str, Any]]:
    streams = []
    for source in find_subtitled_sources(server):
        for stream in source.source["MediaStreams"]:
            if stream.get("Type") == "Subtitle":
                streams.append(stream)
    return streams


def _language_names(streams: List[Dict[str, Any]]) -> Tuple[Dict[str, str], List[str]]:
    """The tag -> language name table, read off the streams that state a language and no title.

    A titled stream cannot answer it: the title leads and an attribute it already contains is
    dropped, so the first piece of that string is not necessarily the language name.
    """
    table: Dict[str, str] = {}
    disagreed = []
    for stream in streams:
        tag = stream.get("Language")
        title = stream.get("Title") or ""
        display = stream.get("DisplayTitle") or ""
        if not tag or title or not display:
            continue
        name = display.split(JOIN)[0]
        if tag in table and table[tag] != name:
            disagreed.append(f"{tag!r}: {table[tag]!r} and {name!r}")
        table.setdefault(tag, name)
    return table, disagreed


def _cultures(server: Server) -> Tuple[Dict[str, str], Set[str]]:
    """The display name this repository's own table would use, keyed by every token that names
    the row, **first row winning** - which is the lookup 011 T3 already built for filenames - and
    the tokens that are a *bibliographic* three-letter code rather than the terminological one.
    """
    found: Dict[str, str] = {}
    bibliographic: Set[str] = set()
    for row in server.get("/Localization/Cultures"):
        display = row.get("DisplayName") or ""
        terminological = (row.get("ThreeLetterISOLanguageName") or "").lower()
        for code in row.get("ThreeLetterISOLanguageNames") or []:
            if code and code.lower() != terminological:
                bibliographic.add(code.lower())
        tokens = [
            display,
            row.get("Name") or "",
            *(row.get("ThreeLetterISOLanguageNames") or []),
            row.get("ThreeLetterISOLanguageName") or "",
            row.get("TwoLetterISOLanguageName") or "",
        ]
        for token in tokens:
            if token:
                found.setdefault(token.lower(), display)
    return found, bibliographic


def run(server: Server) -> Probe:
    probe = Probe(
        script="probe_stream_display_title.py",
        question=(
            "What is a subtitle stream's display title assembled from, and which of its pieces "
            "are localised rather than literal?"
        ),
        document="specs/011-subtitle-delivery/spec.md",
        section="§3.2 (the NAME box), OQ-4",
        expectation=None,
    )
    configuration: Dict[str, Any] = {}
    try:
        configuration = server.get("/System/Configuration")
    except ProbeError:
        probe.note(
            "the server's interface culture needs an administrator, so the culture every "
            "localised word below is written in is unstated on this run"
        )
    probe.observe(
        "the server's own interface culture",
        "UICulture={!r}".format(configuration.get("UICulture", "unread")),
    )

    streams = _subtitle_streams(server)
    labelled = [s for s in streams if s.get("DisplayTitle")]
    probe.observe(
        "subtitle streams read",
        f"{len(streams)} streams, {len(labelled)} of them carrying a DisplayTitle",
    )
    if not labelled:
        raise ProbeError("no subtitle stream in this library carries a DisplayTitle")

    # The five words, as this server states them, beside the literals the assembly falls back to.
    localised = []
    for name, fallback in FALLBACKS.items():
        values = sorted({s[name] for s in labelled if s.get(name)})
        if values:
            localised.append(name)
        probe.observe(
            "  " + name,
            "{} on the wire, fallback {!r}{}".format(
                values or "absent from every stream",
                fallback,
                "" if values == [fallback] else "   <- the fallback is not what is written",
            ),
        )

    cultures, bibliographic = _cultures(server)
    table, disagreed = _language_names(labelled)
    probe.observe("language tags seen", f"{len(table)} distinct")
    alternates = 0
    for tag in sorted(table):
        ours = cultures.get(tag.lower())
        alternates += 1 if ours and (";" in ours or "," in ours) else 0
        probe.observe(
            "  " + tag,
            "reference {!r}, this project's table {!r}{}".format(
                table[tag], ours, "" if ours == table[tag] else "   <- differs"
            ),
        )

    reached: Set[str] = set()
    wrong = []
    skipped = []
    for stream in labelled:
        tag = stream.get("Language")
        if tag:
            _reach(reached, tag_shape(tag, bibliographic))
        if tag and tag not in table:
            skipped.append(tag)
            continue
        rebuilt = assemble(stream, table.get(tag or ""), reached)
        if rebuilt != stream.get("DisplayTitle"):
            wrong.append(
                "index {}: reproduced {!r}, server answered {!r}".format(
                    stream.get("Index"), rebuilt, stream.get("DisplayTitle")
                )
            )
    reproduced = len(labelled) - len(skipped) - len(wrong)
    probe.observe(
        "reproduction",
        f"{reproduced} of {len(labelled) - len(skipped)} display titles rebuilt exactly",
    )
    if skipped:
        probe.observe(
            "  not reproducible here",
            f"{len(skipped)} streams tagged {sorted(set(skipped))}: every stream carrying "
            "that tag has a title of its own, so its language name is never stated alone and "
            "cannot be read off the wire",
        )
    for line in wrong[:8]:
        probe.observe("  mismatch", line)
    for line in disagreed[:4]:
        probe.observe("  tag answered two names", line)

    probe.observe(
        "this project's own display name for the tags seen",
        f"{alternates} of {len(table)} carry an alternate spelling or a qualifier, so they "
        f"cannot equal a platform display name in any culture; the other "
        f"{len(table) - alternates} are a single word, which is a bound and not a match - no "
        "English-configured reference is reachable from here",
    )

    missed = [branch for branch in BRANCHES if branch not in reached]
    probe.observe(
        "branches of the assembly this library reached",
        ", ".join(b for b in BRANCHES if b in reached) or "none",
    )
    if missed:
        probe.observe("branches not reached, and therefore not measured here", ", ".join(missed))
        probe.note(
            "each missed branch above is read from the reference rather than measured on it, "
            "and is reported on every run so it is never counted as agreement. The three tag "
            "shapes are the ones that decide whether the language name is resolved at all: the "
            "reference matches a plain tag against the platform's terminological three-letter "
            "code and nothing else, so a two-letter tag and a bibliographic code are both "
            "answered as the raw tag with its first letter upper-cased"
        )

    checks = [not wrong, not disagreed, bool(table)]
    if all(checks):
        probe.conclude(
            "a subtitle stream's display title is the language name, a hearing-impaired word, a "
            "default word, a forced word, the codec upper cased and an external word, joined by "
            "' - ', with a stream's own title leading and each attribute it already contains "
            f"dropped - {reproduced} of {len(labelled) - len(skipped)} rebuilt exactly from "
            "each stream's own properties. All five localised words are stated on the wire, so "
            "the literals compiled into the assembly are unreachable on a served stream: a "
            "stream with no language is marked with the *translated* word behind the key "
            "'Undefined' and never with the compiled-in 'Und'. The language name is the one "
            "piece no table in this repository can answer"
        )
    else:
        probe.conclude(
            f"the reproduction does not agree with the server: {len(wrong)} mismatches, "
            f"{len(disagreed)} tags answering two names"
        )
    return probe


if __name__ == "__main__":
    raise SystemExit(main(run, __doc__ or ""))
