#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""How does the server derive SortName from Name?

Answers 003 OQ-3, the highest-value single probe in the library feature: SortName decides the
ordering of every list a client shows, so a difference here is visible on every screen.

Method. Media items cannot be created over the API, but playlists can, and a playlist is an
ordinary item whose SortName comes from the same shared derivation - Jellyfin overrides
CreateSortName only for Audio, Episode, Season and LiveTvChannel
[source: MediaBrowser.Controller/Entities/*.cs @ v10.11.11]. So the probe creates playlists with
crafted names, reads back their SortName, and removes them. What it measures is therefore the
*base* rule, which is the one Movies, Series, Albums, Artists and Playlists use.

Each crafted name isolates one transformation, and the observed value is compared against a
reimplementation of the algorithm read from the reference's source. Agreement across the whole set
is much stronger evidence than any single case.

Writes: creates one playlist per case and deletes them all afterwards, including on failure.

Usage:
    python3 tools/probe_sort_names.py http://your-jellyfin:8096 -u username --allow-writes
"""

from __future__ import annotations

import unicodedata

from _probe import Probe, ProbeError, Server, main

# The playlists are created with the crafted name EXACTLY, with no marker of any kind: a prefix
# would stop "The Matrix" starting with an article and a suffix would stop "Matrix The" ending
# with one, which are two of the cases being measured. They are tracked by the id the server
# returns, and removed by it.

# (crafted name, which rule it isolates)
CASES = [
    ("The Matrix", "article at the start"),
    ("Matrix The", "article at the end"),
    ("Once The Time", "article in the middle"),
    ("A Bridge", "single-letter article"),
    ("Amelie", "ascii control for the diacritic case"),
    ("Amélie", "diacritics folded"),
    ("iRobot", "case normalised"),
    ("2 Fast 2 Furious", "two digit runs"),
    ("10 Things", "two-digit run"),
    ("Wall-E", "hyphen"),
    ("Rock & Roll", "ampersand"),
    ("Don't Look Up", "apostrophe"),
    ("S.W.A.T.", "full stops"),
    ("100% Wolf", "percent sign"),
    ("  Padded  ", "surrounding whitespace"),
]

# Defaults read from MediaBrowser.Model/Configuration/ServerConfiguration.cs:115-127 @ v10.11.11.
# They are server configuration, so an operator may have changed them; a mismatch is reported as
# such rather than assumed to be a documentation error.
REMOVE_WORDS = ["the", "a", "an"]
REMOVE_CHARS = [",", "&", "-", "{", "}", "'"]
REPLACE_CHARS = [".", "+", "%"]
DIGIT_PAD = 10

# Audio, Episode and Season override CreateSortName entirely: they build a numeric prefix and
# append the RAW name - no lowercasing, no article removal, no diacritic folding, no digit
# padding. The widths are not uniform, and the asymmetry is theirs, not a transcription error:
# an episode's season is three digits and its episode number four.
# [source: MediaBrowser.Controller/Entities/Audio/Audio.cs:94-98,
#          MediaBrowser.Controller/Entities/TV/Episode.cs:238-242,
#          MediaBrowser.Controller/Entities/TV/Season.cs:149-152 @ v10.11.11]
OVERRIDES = {
    "Audio":   (4, 4, " - "),    # disc, track
    "Episode": (3, 4, " - "),    # season, episode
    "Season":  (4, None, ""),    # season only, no name appended
}


def derive(name: str) -> str:
    """Reimplementation of the reference's derivation, from its source, not from its code."""
    sortable = name.strip().lower()

    for word in REMOVE_WORDS:
        if sortable.startswith(word + " "):
            sortable = sortable[len(word) + 1:]
        sortable = sortable.replace(f" {word} ", " ")
        if sortable.endswith(" " + word):
            sortable = sortable[: -(len(word) + 1)]

    for char in REMOVE_CHARS:
        sortable = sortable.replace(char, "")
    for char in REPLACE_CHARS:
        sortable = sortable.replace(char, " ")

    # Digit runs are left-padded with zeros to a fixed width, which is how lexical comparison
    # produces numeric ordering.
    out, chunk_start, in_digits = [], 0, sortable[:1].isdigit()
    for index, char in enumerate(sortable):
        if char.isdigit() != in_digits:
            chunk = sortable[chunk_start:index]
            out.append(chunk.rjust(DIGIT_PAD, "0") if in_digits else chunk)
            chunk_start, in_digits = index, char.isdigit()
    tail = sortable[chunk_start:]
    out.append(tail.rjust(DIGIT_PAD, "0") if in_digits else tail)
    sortable = "".join(out)

    return "".join(
        c for c in unicodedata.normalize("NFD", sortable) if unicodedata.category(c) != "Mn"
    )


def derive_override(item: dict) -> str | None:
    """Predict SortName for the three types that override the base derivation."""
    widths = OVERRIDES.get(item.get("Type"))
    if widths is None:
        return None
    parent_width, index_width, sep = widths
    parent, index = item.get("ParentIndexNumber"), item.get("IndexNumber")

    if index_width is None:                       # Season: the number alone, or the name
        return f"{parent:0{parent_width}d}" if index is not None else item.get("Name", "")

    prefix = f"{parent:0{parent_width}d}{sep}" if parent is not None else ""
    prefix += f"{index:0{index_width}d}{sep}" if index is not None else ""
    return prefix + item.get("Name", "")


def check_overrides(server: Server, probe: Probe) -> None:
    """Read-only: compare real items of the three overriding types against the source formulas."""
    for item_type in OVERRIDES:
        index_field = "IndexNumber" if item_type != "Season" else "IndexNumber"
        found = server.get(
            "/Items", Recursive="true", IncludeItemTypes=item_type, Fields="SortName",
            Limit=25, SortBy="SortName", UserId=server.user_id,
        )
        items = found.get("Items", [])
        if not items:
            probe.observe(f"{item_type} override", "no items in this library")
            continue

        # Season's formula uses IndexNumber, not ParentIndexNumber.
        agree = 0
        for item in items:
            if item_type == "Season":
                item = {**item, "ParentIndexNumber": item.get(index_field)}
            if item.get("SortName") == derive_override(item):
                agree += 1
        probe.observe(
            f"{item_type} override",
            f"{agree}/{len(items)} match the source formula"
            + ("" if agree == len(items) else "   <-- some may carry a forced sort name"),
        )


def create_playlist(server: Server, name: str, fallback_item: str | None) -> str:
    body = {"Name": name, "Ids": [], "UserId": server.user_id}
    try:
        return server.post("/Playlists", body=body)["Id"]
    except ProbeError:
        if not fallback_item:
            raise
        body["Ids"] = [fallback_item]
        body["MediaType"] = "Audio"
        return server.post("/Playlists", body=body)["Id"]


def run(server: Server) -> Probe:
    probe = Probe(
        script="probe_sort_names.py",
        question="how does the server derive SortName from Name?",
        document="specs/003-library-configuration-and-scanning/spec.md",
        section="section 3.7",
        expectation=(
            "articles dropped, diacritics folded, case normalised, punctuation ignored, and "
            "leading numbers sorting numerically rather than lexically"
        ),
    )

    seed = server.get("/Items", Recursive="true", IncludeItemTypes="Audio", Limit=1,
                      UserId=server.user_id)
    fallback = (seed.get("Items") or [{}])[0].get("Id")

    created: dict[str, str] = {}
    mismatches: list[str] = []
    try:
        for name, _rule in CASES:
            created[name] = create_playlist(server, name, fallback)

        found = server.get(
            "/Items",
            Ids=",".join(created.values()),
            Fields="SortName",
            UserId=server.user_id,
        )
        by_id = {item["Id"]: item for item in found.get("Items", [])}

        for name, rule in CASES:
            item = by_id.get(created[name])
            if item is None:
                probe.observe(repr(name), "not returned by /Items")
                mismatches.append(f"{name!r} could not be read back")
                continue

            observed = item.get("SortName", "")
            predicted = derive(item.get("Name", name))

            agrees = observed == predicted
            detail = f"-> {observed!r}"
            if not agrees:
                detail += f"   <-- derivation predicts {predicted!r}"
                mismatches.append(f"{name!r} gave {observed!r}, predicted {predicted!r}")
            probe.observe(f"{name!r}  [{rule}]", detail)
    finally:
        stranded = []
        for name, item_id in created.items():
            try:
                server.delete(f"/Items/{item_id}")
            except ProbeError:
                stranded.append(f"{name!r} ({item_id})")
        if stranded:
            probe.note(
                "could not delete these probe playlists; remove them by hand: "
                + ", ".join(stranded)
            )

    try:
        check_overrides(server, probe)
    except ProbeError as exc:
        probe.observe("overrides", f"could not be read - {exc}")

    probe.note(
        "The crafted cases measure the base derivation, shared by Movies, Series, Albums, "
        "Artists and Playlists. The override rows below them are read-only checks against real "
        "items of the three types that replace it entirely. A row short of full agreement is not "
        "necessarily a mismatch: an item whose metadata carries an explicit sort title takes that "
        "instead, and the API does not say which items those are."
    )
    probe.note(
        "SortName is predicted from the Name the server echoes back, not from the name that was "
        "sent, so a server that trims or rewrites the name on creation is still measured fairly."
    )
    probe.note(
        "The word and character lists are server configuration, so a mismatch may mean the "
        "operator changed them rather than that the documentation is wrong. Compare against "
        "SortRemoveWords, SortRemoveCharacters and SortReplaceCharacters before concluding."
    )

    if mismatches:
        probe.conclude("; ".join(mismatches), matches_documentation=False)
    else:
        probe.conclude(
            f"all {len(CASES)} cases match the derivation read from the reference's source. "
            "Two refinements the documentation does not yet state: articles are removed at the "
            "start, in the middle and at the end, not only leading; and numeric ordering is "
            f"produced by left-padding every digit run to {DIGIT_PAD} characters, not by "
            "comparing numerically",
            matches_documentation=True,
        )
    return probe


if __name__ == "__main__":
    raise SystemExit(main(run, __doc__.splitlines()[0], needs_writes=True))
