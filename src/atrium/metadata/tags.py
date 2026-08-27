# SPDX-License-Identifier: GPL-3.0-or-later
"""Embedded audio tags, and the seam 003 shipped answering nothing.

003 defined `MetadataSource` and gave it one implementation that knows nothing, so a music library
was resolved entirely from its paths. This module is the real one, and wiring it in is the moment
a well-tagged FLAC stops being filed under the directory it happens to sit in (AC-5).

**One open per file per scan.** `TagSource` memoises, because the same read answers two different
questions: the resolver asks *what album is this file in* while the tree is being built, and the
refresh asks *everything else* afterwards. Opening twice would double the I/O of the one part of a
scan that touches file contents at all.

**Two constraints 003 wrote down for this seam, restated because breaking either is silent**
(003's tasks, "what this feature owes the next ones"):

* the scan consults this source **only** for files whose `(size, mtime_ns)` has moved, so nothing
  it answers may feed an identifier - an identity derived from a tag would make that skip unsound,
  and the symptom would be a music library that doubles its albums on the second scan;
* `tags_for` keeps 003 section 3.5's key vocabulary exactly, including the rule that **an empty
  string is a tag that is present and empty**, which the reference copies.

**Multi-valued stays multi-valued** (spec section 3.3, AC-6). Vorbis repeats keys, ID3v2.4
separates with NUL, MP4 repeats atom entries; mutagen hands all three back as lists and nothing
here joins them. The reverse holds too: a single value containing `;` stays **one** artist,
because the reference splits on custom delimiters only when an operator turns that on and it
defaults to off `[source: MediaBrowser.Model/Configuration/LibraryOptions.cs:37-40 @ v10.11.11]`.
Guessing at separators is how `AC/DC` becomes two artists.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import mutagen
from mutagen.flac import FLAC
from mutagen.id3 import ID3FileType
from mutagen.mp4 import MP4
from mutagen.oggvorbis import OggVorbis

from atrium.metadata.model import Field, FieldValues, PersonCredit, PersonKind

logger = logging.getLogger(__name__)

#: The leading integer of a `3/12`-style number. Everything after the slash is the total, which
#: nothing in v1 serves.
_LEADING_NUMBER = re.compile(r"\s*(\d+)")

#: A four-digit year at the start of a date tag: `1998`, `1998-05-04`, `1998/05/04`.
_LEADING_YEAR = re.compile(r"\s*(\d{4})")


@dataclass(frozen=True, slots=True)
class EmbeddedArt:
    """Cover art carried inside the audio file.

    Becomes a `Primary` image **only when no file-based one exists** (spec section 3.4); this
    module reports it and `metadata/artwork.py` decides.
    """

    data: bytes
    mime: str = ""


@dataclass(frozen=True, slots=True)
class TagResult:
    """One audio file's tags, in both vocabularies at once.

    Two views of one read, rather than two reads: `values` is 004's field vocabulary for the
    merge, `tags` is 003's seam vocabulary for the resolver. They are deliberately not the same
    shape - `tags` maps to single strings because that is what the seam promised, and `values`
    keeps the lists because that is what AC-6 is about.
    """

    values: FieldValues = field(default_factory=dict)
    tags: Mapping[str, str] = field(default_factory=dict)
    art: EmbeddedArt | None = None
    warning: str = ""
    """Why nothing was read, when nothing was. An unreadable tag block is a warning and the item
    resolves from what remains (spec section 3.3) - never a failure."""


# ----------------------------------------------------------------------------------------------
# Reading
# ----------------------------------------------------------------------------------------------


def read_tags(path: Path) -> TagResult:
    """Everything embedded in the file at `path`. Never raises.

    A truncated file, an unknown ID3 version, a tag block that decodes to mojibake: all of them
    are the warn-and-continue path, and the caller gets an empty result with a reason.
    """
    try:
        opened = mutagen.File(path)
    except Exception as exc:  # mutagen raises a different type per container
        return TagResult(warning=f"{path}: {type(exc).__name__}: {exc}")

    if opened is None:
        return TagResult(warning=f"{path}: not a container mutagen recognises")
    if opened.tags is None:
        # A perfectly good file with no tag block at all. Not a warning: most of a library looks
        # like this before anybody tags it, and the path still resolves the track.
        return TagResult(art=_art(opened))

    try:
        raw = _raw_tags(opened)
    except Exception as exc:  # a malformed frame can raise from deep inside
        return TagResult(warning=f"{path}: {type(exc).__name__}: {exc}")

    return TagResult(values=_values(raw), tags=_seam(raw), art=_art(opened))


#: The internal vocabulary the three container readers agree on, so the mapping to `Field` and to
#: 003's seam is written once rather than three times.
_Raw = dict[str, list[str]]


def _raw_tags(opened: Any) -> _Raw:
    if isinstance(opened, (FLAC, OggVorbis)) or _is_vorbis(opened):
        return _from_vorbis(opened.tags)
    if isinstance(opened, MP4):
        return _from_mp4(opened.tags)
    if isinstance(opened, ID3FileType) or hasattr(opened.tags, "getall"):
        return _from_id3(opened.tags)
    return {}


def _is_vorbis(opened: Any) -> bool:
    """Opus and Ogg FLAC carry Vorbis comments too, and mutagen gives them their own classes.

    Tested by shape rather than by listing every class, so a container mutagen learns about later
    is read rather than ignored - which is the failure mode worth avoiding here, since ignoring a
    tag block silently files a well-tagged track under its directory.
    """
    tags = getattr(opened, "tags", None)
    return tags is not None and hasattr(tags, "get") and hasattr(tags, "as_dict")


#: Vorbis comment field names, lowercased by mutagen already.
_VORBIS: Mapping[str, str] = {
    "title": "title",
    "artist": "artist",
    "albumartist": "albumartist",
    "album": "album",
    "tracknumber": "track",
    "discnumber": "disc",
    "date": "date",
    "originaldate": "originaldate",
    "genre": "genre",
    "composer": "composer",
    "musicbrainz_trackid": "MusicBrainzTrack",
    "musicbrainz_releasetrackid": "MusicBrainzTrack",
    "musicbrainz_recordingid": "MusicBrainzRecording",
    "musicbrainz_albumid": "MusicBrainzAlbum",
    "musicbrainz_releasegroupid": "MusicBrainzReleaseGroup",
    "musicbrainz_artistid": "MusicBrainzArtist",
    "musicbrainz_albumartistid": "MusicBrainzAlbumArtist",
    "replaygain_track_gain": "gain",
}


def _from_vorbis(tags: Any) -> _Raw:
    found: _Raw = {}
    for key, values in tags.items():
        mapped = _VORBIS.get(key.lower())
        if mapped is not None:
            found.setdefault(mapped, []).extend(str(one) for one in values)
    return found


#: ID3 frame ids. `TPE2` is the album artist by long convention rather than by the standard, which
#: calls it "band/orchestra/accompaniment" - every tagger writes the album artist there.
_ID3: Mapping[str, str] = {
    "TIT2": "title",
    "TPE1": "artist",
    "TPE2": "albumartist",
    "TALB": "album",
    "TRCK": "track",
    "TPOS": "disc",
    "TDRC": "date",
    "TYER": "date",
    "TDOR": "originaldate",
    "TCON": "genre",
    "TCOM": "composer",
}

#: `TXXX` frames, keyed by their description. MusicBrainz's own tagger writes these spellings.
_ID3_TXXX: Mapping[str, str] = {
    "musicbrainz album id": "MusicBrainzAlbum",
    "musicbrainz release group id": "MusicBrainzReleaseGroup",
    "musicbrainz artist id": "MusicBrainzArtist",
    "musicbrainz album artist id": "MusicBrainzAlbumArtist",
    "musicbrainz release track id": "MusicBrainzTrack",
    "replaygain_track_gain": "gain",
}


def _from_id3(tags: Any) -> _Raw:
    found: _Raw = {}
    for frame_id, mapped in _ID3.items():
        frame = tags.get(frame_id)
        if frame is not None and getattr(frame, "text", None):
            found.setdefault(mapped, []).extend(str(one) for one in frame.text)
    for frame in tags.getall("TXXX"):
        described = _ID3_TXXX.get(str(frame.desc).lower())
        if described is not None:
            found.setdefault(described, []).extend(str(one) for one in frame.text)
    for frame in tags.getall("UFID"):
        # The recording id, and the one identifier MusicBrainz's own tagger writes as a UFID
        # rather than a TXXX.
        if "musicbrainz" in str(frame.owner).lower():
            decoded = frame.data.decode("utf-8", "replace")
            found.setdefault("MusicBrainzRecording", []).append(decoded)
    return found


#: MP4 atoms. The four-character ones are Apple's; the `----` ones are free-form and carry the
#: same names the Vorbis and ID3 worlds use.
_MP4: Mapping[str, str] = {
    "\xa9nam": "title",
    "\xa9ART": "artist",
    "aART": "albumartist",
    "\xa9alb": "album",
    "\xa9day": "date",
    "\xa9gen": "genre",
    "\xa9wrt": "composer",
}

_MP4_FREEFORM: Mapping[str, str] = {
    "musicbrainz track id": "MusicBrainzTrack",
    "musicbrainz release track id": "MusicBrainzTrack",
    "musicbrainz album id": "MusicBrainzAlbum",
    "musicbrainz release group id": "MusicBrainzReleaseGroup",
    "musicbrainz artist id": "MusicBrainzArtist",
    "musicbrainz album artist id": "MusicBrainzAlbumArtist",
    "replaygain_track_gain": "gain",
}


def _from_mp4(tags: Any) -> _Raw:
    found: _Raw = {}
    for atom, mapped in _MP4.items():
        values = tags.get(atom)
        if values:
            found.setdefault(mapped, []).extend(str(one) for one in values)
    # `trkn` and `disk` are pairs of integers rather than text, which is the one place MP4 is
    # tidier than the others: no `3/12` to parse.
    for atom, mapped in (("trkn", "track"), ("disk", "disc")):
        pairs = tags.get(atom)
        if pairs:
            number = pairs[0][0] if isinstance(pairs[0], tuple) else pairs[0]
            if number:
                found[mapped] = [str(number)]
    for atom, values in tags.items():
        if not atom.startswith("----:"):
            continue
        freeform = _MP4_FREEFORM.get(atom.rsplit(":", 1)[-1].lower())
        if freeform is not None:
            found.setdefault(freeform, []).extend(_freeform(values))
    return found


def _freeform(values: Iterable[Any]) -> list[str]:
    return [
        bytes(one).decode("utf-8", "replace") if isinstance(one, (bytes, bytearray)) else str(one)
        for one in values
    ]


def _art(opened: Any) -> EmbeddedArt | None:
    """The first embedded picture, whichever way this container carries one."""
    pictures = getattr(opened, "pictures", None)
    if pictures:
        return EmbeddedArt(data=bytes(pictures[0].data), mime=str(pictures[0].mime))

    tags = getattr(opened, "tags", None)
    if tags is None:
        return None

    getall = getattr(tags, "getall", None)
    if getall is not None:
        frames = getall("APIC")
        if frames:
            return EmbeddedArt(data=bytes(frames[0].data), mime=str(frames[0].mime))

    covers = tags.get("covr", None) if hasattr(tags, "get") else None
    if covers:
        cover = covers[0]
        formats = {13: "image/jpeg", 14: "image/png"}
        kind = formats.get(getattr(cover, "imageformat", 0), "")
        return EmbeddedArt(data=bytes(cover), mime=kind)
    return None


# ----------------------------------------------------------------------------------------------
# The two vocabularies
# ----------------------------------------------------------------------------------------------


def _values(raw: _Raw) -> dict[Field, object]:
    """004's field vocabulary. Lists stay lists (AC-6)."""
    values: dict[Field, object] = {}

    if title := _first(raw, "title"):
        values[Field.NAME] = title
    if artists := raw.get("artist"):
        values[Field.ARTISTS] = list(artists)
    if album_artists := raw.get("albumartist"):
        values[Field.ALBUM_ARTISTS] = list(album_artists)
    if genres := raw.get("genre"):
        values[Field.GENRES] = list(genres)

    if (track := _number(raw, "track")) is not None:
        values[Field.INDEX_NUMBER] = track
    if (disc := _number(raw, "disc")) is not None:
        values[Field.PARENT_INDEX_NUMBER] = disc

    if (year := _year(raw)) is not None:
        values[Field.YEAR] = year
    if (premiere := _date(raw)) is not None:
        values[Field.PREMIERE_DATE] = premiere

    if composers := raw.get("composer"):
        values[Field.PEOPLE] = [
            PersonCredit(name=name, kind=PersonKind.COMPOSER) for name in composers if name.strip()
        ]

    if ids := {
        name: values_for[0]
        for name, values_for in raw.items()
        if name.startswith("MusicBrainz") and values_for and values_for[0].strip()
    }:
        values[Field.PROVIDER_IDS] = ids

    if (gain := _gain(raw)) is not None:
        values[Field.NORMALIZATION_GAIN] = gain

    return values


def _seam(raw: _Raw) -> dict[str, str]:
    """003 section 3.5's vocabulary, and nothing else.

    **An empty string is kept**, because in this vocabulary a present-and-empty tag is a different
    thing from an absent one and the reference copies both. `values` above drops it, because there
    an empty string is not a value - two rules, two homes, and conflating them breaks one feature
    or the other silently.

    A multi-valued tag contributes its **first** value here, because the seam promised one string
    per key. The full list survives in `values`, so AC-6 is unaffected: what a client sees as three
    artists comes from there, and what an album's identity is derived from comes from here.
    """
    tags: dict[str, str] = {}
    for key, name in (
        ("title", "title"),
        ("artist", "artist"),
        ("albumartist", "albumartist"),
        ("album", "album"),
        ("track", "track"),
        ("disc", "disc"),
    ):
        if raw.get(key):
            tags[name] = raw[key][0]
    if (year := _year(raw)) is not None:
        tags["year"] = str(year)
    return tags


def _first(raw: _Raw, key: str) -> str | None:
    values = raw.get(key)
    return values[0] if values and values[0].strip() else None


def _number(raw: _Raw, key: str) -> int | None:
    text = _first(raw, key)
    if text is None:
        return None
    match = _LEADING_NUMBER.match(text)
    return int(match.group(1)) if match else None


def _year(raw: _Raw) -> int | None:
    text = _first(raw, "date") or _first(raw, "originaldate")
    if text is None:
        return None
    match = _LEADING_YEAR.match(text)
    return int(match.group(1)) if match else None


def _date(raw: _Raw) -> datetime | None:
    """A full date, only when the tag carries one. `1998` alone is a year and not a date.

    Midnight UTC, because `PremiereDate` is a date-time on the wire and the conversion belongs at
    ingestion (architecture section 4).
    """
    text = _first(raw, "date")
    if text is None or len(text) < 10:
        return None
    try:
        parsed = date.fromisoformat(text[:10].replace("/", "-"))
    except ValueError:
        return None
    return datetime(parsed.year, parsed.month, parsed.day, tzinfo=UTC)


def _gain(raw: _Raw) -> float | None:
    """The track gain in decibels, the one replay-gain value the reference reads and serves.

    The trailing unit is stripped exactly as the reference strips it - case-insensitively, two
    characters `[source: MediaBrowser.Providers/MediaInfo/AudioFileProber.cs:362-375 @ v10.11.11]`
    - and a value that is not finite is discarded rather than stored.
    """
    text = _first(raw, "gain")
    if text is None:
        return None
    cleaned: str = text.strip()
    if cleaned[-2:].lower() == "db":
        cleaned = cleaned[:-2].strip()
    try:
        parsed = float(cleaned)
    except ValueError:
        return None
    return parsed if -1e6 < parsed < 1e6 else None


# ----------------------------------------------------------------------------------------------
# The seam
# ----------------------------------------------------------------------------------------------


class TagSource:
    """003's `MetadataSource`, reading real files, with one open per file per scan.

    Constructed per scan and thrown away with it: the memo has no expiry because a scan's lifetime
    *is* its expiry, and a source that outlived one would answer a later scan from a file that had
    since changed.
    """

    def __init__(self, roots: Sequence[Path] | Path) -> None:
        self._roots: tuple[Path, ...] = (roots,) if isinstance(roots, Path) else tuple(roots)
        self._memo: dict[str, TagResult] = {}

    def tags_for(self, relative_path: str) -> Mapping[str, str]:
        """003's contract: whatever is embedded, in its vocabulary. Empty when nothing is known."""
        return self.result_for(relative_path).tags

    def result_for(self, relative_path: str) -> TagResult:
        """The whole read, memoised. The refresh's half of the same question."""
        cached = self._memo.get(relative_path)
        if cached is None:
            cached = read_tags(self._resolve(relative_path))
            self._memo[relative_path] = cached
        return cached

    def _resolve(self, relative_path: str) -> Path:
        """A library may have several roots and a relative path does not say which.

        The first root that has the file wins. That is not a guess: 003 already derives one
        identity from `(library, relative path)`, so the same relative path under two roots is
        already **one item** there - resolving it to one file here agrees with that rather than
        inventing a second answer.
        """
        for root in self._roots:
            candidate = root / relative_path
            if candidate.is_file():
                return candidate
        return (self._roots[0] if self._roots else Path()) / relative_path

    def results(self) -> Iterable[TagResult]:
        """Every read this source has memoised, for the report."""
        return self._memo.values()

    @property
    def opened(self) -> int:
        """How many distinct files this source has read. The memo's own test."""
        return len(self._memo)


def warnings_of(sources: Sequence[TagSource]) -> list[str]:
    """Every warning every memoised read produced, for the scan report."""
    return [result.warning for source in sources for result in source.results() if result.warning]


__all__ = [
    "EmbeddedArt",
    "TagResult",
    "TagSource",
    "read_tags",
    "warnings_of",
]
