# SPDX-License-Identifier: GPL-3.0-or-later
"""`.nfo` sidecars: finding them, refusing the dangerous ones, and reading the rest.

The de-facto standard shared with Kodi, and the reason it matters is that a large fraction of
existing libraries already have these files (spec section 3.2). Reading them is the difference
between "Atrium found my library" and "Atrium lost my metadata".

**The parser is built rather than called**, and that is the one surprise in this module. Plan
section 6.2 originally said stdlib `ElementTree` "refuses DTDs and entity definitions outright,
which turns the whole XXE class into the malformed-sidecar path". Measured (Python 3.14.6, expat
1.3.0), it does none of that:

| Input | `ElementTree.parse` as it comes |
|---|---|
| A document type declaration defining an entity | parses, and **expands** it into the value |
| The same, but the entity is external | raises - so no file is ever fetched, but by *failing* |
| Nested entities, five levels of ten | parses, and expands 400 bytes into 200,000 characters |

So the XXE class is closed by default and the **expansion** class is wide open: a `.nfo` a user
drops into a library could cost a scan an arbitrary amount of memory. `_parse` is an
`xml.parsers.expat` parser feeding an `ElementTree.TreeBuilder`, with a handler that refuses a
document type declaration before a single entity is expanded. No real `.nfo` has one, so refusing
the whole construct costs nothing a user will notice and removes the class rather than the
instance.

**Everything else here was measured against the reference's own parser**, and three of its rules
are ones nobody would arrive at by reasoning:

* a `<genre>` containing `/` is **split**, one genre per part;
* `<director>` and `<writer>` split on `|` or `;` when either is present and on `,` otherwise -
  which is what stops `Matthew, Jr.` becoming two people in a list that uses pipes;
* a `<year>` at or below 1850 is **ignored**.

**Nothing here writes.** A sidecar is read; it is never corrected, reformatted or created
(spec section 2).
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ElementTree
import xml.parsers.expat as expat
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import StrEnum
from pathlib import Path

from atrium.compat.ticks import from_timedelta
from atrium.domain.items import ItemType
from atrium.metadata.model import (
    Field,
    FieldValues,
    MetadataField,
    PersonCredit,
    PersonKind,
)

logger = logging.getLogger(__name__)

#: Bigger than any real sidecar by three orders of magnitude. A file over this is treated as
#: malformed rather than read, because the cost of a very large one should be a warning and not
#: the scan (plan section 6.2).
MAX_BYTES = 5 * 1024 * 1024

#: Which file names carry which item's metadata (spec section 3.2's table).
#:
#: **A track has no row**, and that is the table's answer rather than an omission here: music
#: metadata comes from the file's own tags, and the sidecar in music's provider chain is the one
#: beside its album or its artist.
FOLDER_SIDECAR: Mapping[ItemType, str] = {
    ItemType.SERIES: "tvshow.nfo",
    ItemType.SEASON: "season.nfo",
    ItemType.MUSIC_ALBUM: "album.nfo",
    ItemType.MUSIC_ARTIST: "artist.nfo",
    ItemType.MOVIE: "movie.nfo",
}

#: The types whose sidecar sits beside the file and is named after it.
BESIDE_THE_FILE: frozenset[ItemType] = frozenset({ItemType.MOVIE, ItemType.EPISODE})

#: The date format the reference parses these elements with, exactly - it is configurable there and
#: this is its default `[source: MediaBrowser.Model/Configuration/XbmcMetadataOptions.cs:9 @
#: v10.11.11]`. Exact rather than lenient on purpose: a sidecar whose date is written some other
#: way leaves the premiere date to the next provider, which is what the reference does with it.
DATE_FORMAT = "%Y-%m-%d"

#: A year at or below this is discarded `[source:
#: MediaBrowser.XbmcMetadata/Parsers/BaseNfoParser.cs:527-532 @ v10.11.11]`. The reference offers
#: no reason; the effect is that `<year>0</year>` and `<year>1</year>` - which sidecar generators
#: do write for "unknown" - leave the year to the next provider rather than filing a film under
#: the year zero.
EARLIEST_YEAR = 1850


class NfoProblem(StrEnum):
    """Why a sidecar produced nothing. Every one of these is a warning, never a failure: the item
    still resolves from the remaining providers (spec section 3.2, AC-4)."""

    UNREADABLE = "could not be read"
    TOO_LARGE = f"is larger than {MAX_BYTES // (1024 * 1024)} MB, so it was not parsed"
    MALFORMED = "is not well-formed XML"
    HAS_A_DOCUMENT_TYPE = (
        "carries a document type declaration, which this parser refuses before expanding anything"
    )


@dataclass(frozen=True, slots=True)
class NfoWarning:
    """One sidecar that could not be used, named so the user can fix it (AC-4)."""

    path: Path
    problem: NfoProblem
    detail: str = ""

    def __str__(self) -> str:
        detail = f": {self.detail}" if self.detail else ""
        return f"{self.path} {self.problem.value}{detail}"


@dataclass(frozen=True, slots=True)
class NfoResult:
    """What one sidecar said.

    `values` is empty when the file could not be used, and `warnings` says why. The two locks are
    **not** in `values` because they are not values a provider supplies: they constrain what every
    provider may do, which is a different thing (`metadata/model.py`).
    """

    values: FieldValues = field(default_factory=dict)
    warnings: tuple[NfoWarning, ...] = ()

    is_locked: bool | None = None
    """`<lockdata>`: no provider may change anything about this item. `None` when unsaid."""

    locked_fields: tuple[MetadataField, ...] | None = None
    """`<lockedfields>`: the reference's nine, pipe-separated. `None` when unsaid.

    **The sidecar is the only way a lock reaches an item in v1** - spec section 3.6 gives locks no
    HTTP route - so without this element AC-10 would be a criterion about a state nothing could
    produce.
    """


class _RefusedDocumentTypeError(Exception):
    """Raised by the handler that sees a `<!DOCTYPE`, before any entity has been expanded."""


# ----------------------------------------------------------------------------------------------
# Discovery
# ----------------------------------------------------------------------------------------------


def find_sidecar(directory: Path, kind: ItemType, stem: str | None = None) -> Path | None:
    """The sidecar for an item of `kind` in `directory`, or `None`.

    `stem` is the item's first file's name without its extension, for the two types whose sidecar
    is named after the file. A film is looked up **twice**: `Film (1999).nfo` beside it, then
    `movie.nfo` in its folder, which is the folder-per-film layout of spec section 3.2's table. The
    order is the table's order and it matters: a folder holding two films has a `movie.nfo` that
    can only describe one of them, so the per-file name has to win.
    """
    for candidate in _candidates(directory, kind, stem):
        if candidate.is_file():
            return candidate
    return None


def _candidates(directory: Path, kind: ItemType, stem: str | None) -> Iterator[Path]:
    if stem and kind in BESIDE_THE_FILE:
        yield directory / f"{stem}.nfo"
    folder_name = FOLDER_SIDECAR.get(kind)
    if folder_name is not None:
        yield directory / folder_name


# ----------------------------------------------------------------------------------------------
# Reading
# ----------------------------------------------------------------------------------------------


def read_nfo(path: Path, kind: ItemType) -> NfoResult:
    """Everything `path` says about an item of `kind`. Never raises.

    A sidecar that cannot be used is a warning naming the file, and the item resolves from the
    remaining providers (AC-4). That is the whole of this function's error handling, because every
    failure here has the same consequence for the caller.
    """
    root, warning = _read(path)
    if root is None:
        return NfoResult(warnings=(warning,) if warning else ())

    values: dict[Field, object] = {}
    people: list[PersonCredit] = []
    genres: list[str] = []
    studios: list[str] = []
    tags: list[str] = []
    is_locked: bool | None = None
    locked: tuple[MetadataField, ...] | None = None

    for element in root:
        name = element.tag.lower()
        text = (element.text or "").strip()

        if name in ("title", "localtitle", "name"):
            _set(values, Field.NAME, text)
        elif name == "originaltitle":
            _set(values, Field.ORIGINAL_TITLE, text)
        elif name in ("sorttitle", "sortname"):
            _set(values, Field.SORT_NAME, text)
        elif name in ("plot", "biography"):
            _set(values, Field.OVERVIEW, text)
        elif name == "tagline":
            _set(values, Field.TAGLINE, text)
        elif name == "mpaa":
            _set(values, Field.OFFICIAL_RATING, text)
        elif name == "year":
            _year(values, text)
        elif name in ("premiered", "aired", "releasedate", "formed"):
            _premiere_date(values, text)
        elif name == "runtime":
            _runtime(values, text)
        elif name == "rating":
            _community_rating(values, text)
        elif name == "genre":
            genres.extend(_split_on_slash(text))
        elif name == "studio":
            if text:
                studios.append(text)
        elif name in ("tag", "style"):
            if text:
                tags.append(text)
        elif name == "actor":
            person = _actor(element)
            if person is not None:
                people.append(person)
        elif name == "director":
            people.extend(_person_array(text, PersonKind.DIRECTOR))
        elif name == "writer":
            people.extend(_person_array(text, PersonKind.WRITER))
        elif name == "credits":
            people.extend(
                PersonCredit(name=part, kind=PersonKind.WRITER) for part in _split_on_slash(text)
            )
        elif name == "uniqueid":
            _unique_id(values, element)
        elif name == "id":
            _id_element(values, element, text)
        elif name == "lockdata":
            is_locked = text.lower() == "true"
        elif name == "lockedfields":
            locked = _locked_fields(text)
        elif name.endswith("id"):
            _provider_element(values, name, text)

    for key, collected in (
        (Field.GENRES, genres),
        (Field.STUDIOS, studios),
        (Field.TAGS, tags),
    ):
        if collected:
            values[key] = collected
    if people:
        values[Field.PEOPLE] = people
    if not values.get(Field.PROVIDER_IDS):
        # `<id>whatever kodi wrote</id>` matches the element and yields nothing. An empty map is
        # not a value (spec section 3.1), and leaving the key present would make this source look
        # as though it had spoken about provider ids when it had not.
        values.pop(Field.PROVIDER_IDS, None)

    return NfoResult(values=values, warnings=(), is_locked=is_locked, locked_fields=locked)


def _read(path: Path) -> tuple[ElementTree.Element | None, NfoWarning | None]:
    """The bytes, the size cap, and the parse - the three ways this can end in a warning."""
    try:
        if path.stat().st_size > MAX_BYTES:
            return None, NfoWarning(path, NfoProblem.TOO_LARGE)
        raw = path.read_bytes()
    except OSError as exc:
        return None, NfoWarning(path, NfoProblem.UNREADABLE, exc.strerror or str(exc))

    try:
        return _parse(raw), None
    except _RefusedDocumentTypeError:
        return None, NfoWarning(path, NfoProblem.HAS_A_DOCUMENT_TYPE)
    except expat.ExpatError as exc:
        return None, NfoWarning(path, NfoProblem.MALFORMED, str(exc))


def _parse(raw: bytes) -> ElementTree.Element:
    """Expat, feeding a tree builder, refusing a document type declaration outright.

    `ElementTree.parse` cannot do this: it exposes no hook for the declaration, and by the time it
    hands back a tree the entities are already expanded. Everything here is standard library; the
    only unusual line is the handler that raises.
    """
    builder = ElementTree.TreeBuilder()
    parser = expat.ParserCreate()
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)

    def refuse(*_: object) -> None:
        raise _RefusedDocumentTypeError

    parser.StartDoctypeDeclHandler = refuse
    parser.StartElementHandler = lambda tag, attributes: builder.start(tag, attributes)
    parser.EndElementHandler = builder.end
    parser.CharacterDataHandler = builder.data
    parser.Parse(raw, True)
    return builder.close()


# ----------------------------------------------------------------------------------------------
# The field map
# ----------------------------------------------------------------------------------------------


def _set(values: dict[Field, object], key: Field, text: str) -> None:
    """Record `text` under `key`, first element wins, empty ignored.

    Empty is ignored rather than recorded-as-empty because a sidecar with `<plot></plot>` must
    leave the overview to the next provider (spec section 3.1) - and an absent key is how this
    module says "nothing to say".
    """
    if text and key not in values:
        values[key] = text


def _year(values: dict[Field, object], text: str) -> None:
    try:
        year = int(text)
    except ValueError:
        return
    if year > EARLIEST_YEAR:
        values[Field.YEAR] = year


def _premiere_date(values: dict[Field, object], text: str) -> None:
    """Exactly `yyyy-MM-dd`, and it supplies the year when nothing else has.

    The second half is the reference's, not a convenience: `ProductionYear ??= releaseDate.Year`
    `[source: MediaBrowser.XbmcMetadata/Parsers/BaseNfoParser.cs:546-558 @ v10.11.11]`. A sidecar
    with a premiere date and no `<year>` therefore has a year, and one with both keeps the `<year>`
    even when the two disagree.
    """
    try:
        parsed = date.fromisoformat(text) if _looks_like_the_format(text) else None
    except ValueError:
        parsed = None
    if parsed is None:
        return
    values[Field.PREMIERE_DATE] = parsed
    values.setdefault(Field.YEAR, parsed.year)


def _looks_like_the_format(text: str) -> bool:
    """`date.fromisoformat` accepts more than `yyyy-MM-dd` - `20260827` and `2026-W35-1` among
    them - and the reference accepts exactly one format. This keeps the two the same."""
    return len(text) == 10 and text[4] == "-" and text[7] == "-"


def _runtime(values: dict[Field, object], text: str) -> None:
    """Minutes to ticks, **converted here and nowhere else** (architecture section 4).

    Only the text before the first space is read, which is the reference's own leniency and the
    reason `<runtime>97 min</runtime>` works `[source:
    MediaBrowser.XbmcMetadata/Parsers/BaseNfoParser.cs:418-425 @ v10.11.11]`.
    """
    try:
        minutes = int(text.split(" ", 1)[0])
    except ValueError:
        return
    values[Field.RUNTIME] = from_timedelta(timedelta(minutes=minutes))


def _community_rating(values: dict[Field, object], text: str) -> None:
    """A comma is a decimal point here. The reference replaces it before parsing, because half of
    Europe writes `7,4` `[source: MediaBrowser.XbmcMetadata/Parsers/BaseNfoParser.cs:534-541 @
    v10.11.11]`."""
    try:
        values[Field.COMMUNITY_RATING] = float(text.replace(",", "."))
    except ValueError:
        return


def _split_on_slash(text: str) -> list[str]:
    """`Science Fiction / Fantasy` is **two** genres.

    Plan section 6.2 said the opposite - "a single element containing ` / ` is **not** split - the
    reference's parser does not" - and the reference's parser does, on a bare `/`, trimming each
    part `[source: MediaBrowser.XbmcMetadata/Parsers/BaseNfoParser.cs:566-583 @ v10.11.11]`. Not
    splitting would give Atrium a genre no reference server has, on a file both read.

    The cost is real and is the reference's to own: a genre legitimately containing a slash
    becomes two. It applies to `<genre>` and `<credits>` and to nothing else.
    """
    return [part.strip() for part in text.split("/") if part.strip()]


def _person_array(text: str, kind: PersonKind) -> list[PersonCredit]:
    """`<director>` and `<writer>` hold a list, and **which separator depends on the content**.

    A pipe or a semicolon anywhere makes those the separators; otherwise it is the comma. That is
    what keeps `Matthew, Jr.` one person in a list written with pipes
    `[source: MediaBrowser.Controller/Extensions/XmlReaderExtensions.cs @ v10.11.11]`.
    """
    separators = "|;" if ("|" in text or ";" in text) else ","
    parts: list[str] = [text]
    for separator in separators:
        parts = [piece for part in parts for piece in part.split(separator)]
    return [PersonCredit(name=part.strip(), kind=kind) for part in parts if part.strip()]


def _actor(element: ElementTree.Element) -> PersonCredit | None:
    """`<actor>` with `<name>`, `<role>`, `<type>` and `<order>`.

    `<type>` defaults to `Actor` and is matched case-insensitively; a value the vocabulary does not
    know falls back to `Actor` rather than being dropped, which is the reference's behaviour and
    the reason `PersonKind` carries all twenty-five members.
    """
    name = _child_text(element, "name")
    if not name:
        return None
    return PersonCredit(
        name=name,
        kind=_person_kind(_child_text(element, "type")),
        role=_child_text(element, "role") or None,
        sort_order=_child_int(element, ("order", "sortorder")),
    )


def _person_kind(text: str) -> PersonKind:
    lowered = text.lower()
    for member in PersonKind:
        if member.value.lower() == lowered:
            return member
    return PersonKind.ACTOR


def _child_text(element: ElementTree.Element, name: str) -> str:
    for child in element:
        if child.tag.lower() == name:
            return (child.text or "").strip()
    return ""


def _child_int(element: ElementTree.Element, names: Iterable[str]) -> int | None:
    for name in names:
        text = _child_text(element, name)
        if text:
            try:
                return int(text)
            except ValueError:
                return None
    return None


# ----------------------------------------------------------------------------------------------
# Provider identifiers
# ----------------------------------------------------------------------------------------------


def _unique_id(values: dict[Field, object], element: ElementTree.Element) -> None:
    """`<uniqueid type="tmdb">11111</uniqueid>`, the modern spelling.

    The `default="true"` attribute is **not** consulted, which is the reference's behaviour: every
    `uniqueid` is stored, and nothing here decides which one a matcher would prefer, because
    nothing has to - spec section 3.5 rule 1 uses whichever id the provider being asked recognises.
    """
    provider = (element.get("type") or "").strip()
    value = (element.text or "").strip()
    if provider and value:
        _provider_ids(values)[_canonical_provider(provider)] = value


def _id_element(values: dict[Field, object], element: ElementTree.Element, text: str) -> None:
    """Kodi's older `<id TMDB="…" TVDB="…" IMDB="…">tt0000000</id>`.

    The element's own content is taken as an IMDb id **only when it starts with `tt`** - Kodi's
    documentation says the content is arbitrary, so the reference parses it only when it matches a
    shape it recognises `[source: MediaBrowser.XbmcMetadata/Parsers/MovieNfoParser.cs:51-68 @
    v10.11.11]`.
    """
    ids = _provider_ids(values)
    for attribute, provider in (("TMDB", "Tmdb"), ("TVDB", "Tvdb"), ("IMDB", "Imdb")):
        value = (element.get(attribute) or "").strip()
        if value:
            ids[provider] = value
    if "Imdb" not in ids and text.startswith("tt"):
        ids["Imdb"] = text


def _provider_element(values: dict[Field, object], name: str, text: str) -> None:
    """`<tmdbid>`, `<imdbid>`, `<musicbrainzalbumid>` - any element whose name is a provider's
    key with `Id` appended.

    The reference reaches these through its parser's `default:` branch rather than through a case
    of its own, matching the element name case-insensitively against `<Key>Id` for every registered
    provider `[source: MediaBrowser.XbmcMetadata/Parsers/BaseNfoParser.cs:640-650 @ v10.11.11]` -
    which is why a `.nfo` its own saver writes round-trips even though no `case "tmdbid"` exists.
    """
    if text:
        _provider_ids(values)[_canonical_provider(name[: -len("id")])] = text


#: The spellings the reference normalises to, plus the two aliases it hard-codes
#: `[source: MediaBrowser.XbmcMetadata/Parsers/BaseNfoParser.cs:108-111 @ v10.11.11]`.
#:
#: A key not in here is stored as written. That is the reference's behaviour and it is also the
#: only safe one: a provider this build has never heard of is still the user's decision about what
#: this film is, and discarding it would make the next refresh guess (spec section 3.2).
_PROVIDER_SPELLINGS: Mapping[str, str] = {
    "tmdb": "Tmdb",
    "tmdbcollection": "TmdbCollection",
    "collectionnumber": "TmdbCollection",
    "tmdbcol": "TmdbCollection",
    "tmdbcolid": "TmdbCollection",
    "imdb": "Imdb",
    "imdb_": "Imdb",
    "tvdb": "Tvdb",
    "tvdbslug": "TvdbSlug",
    "tvmaze": "TvMaze",
    "tvrage": "TvRage",
    "zap2it": "Zap2It",
    "musicbrainzalbum": "MusicBrainzAlbum",
    "musicbrainzalbumartist": "MusicBrainzAlbumArtist",
    "musicbrainzartist": "MusicBrainzArtist",
    "musicbrainzreleasegroup": "MusicBrainzReleaseGroup",
    "musicbrainztrack": "MusicBrainzTrack",
    "musicbrainzrecording": "MusicBrainzRecording",
    "audiodbalbum": "AudioDbAlbum",
    "audiodbartist": "AudioDbArtist",
}


def _canonical_provider(raw: str) -> str:
    return _PROVIDER_SPELLINGS.get(raw.strip().lower(), raw.strip())


def _provider_ids(values: dict[Field, object]) -> dict[str, str]:
    existing = values.get(Field.PROVIDER_IDS)
    if not isinstance(existing, dict):
        existing = {}
        values[Field.PROVIDER_IDS] = existing
    return existing


def _locked_fields(text: str) -> tuple[MetadataField, ...] | None:
    """`Name|Genres|Cast`, matched case-insensitively, **unknown tokens dropped**.

    Dropped rather than refused, which is the reference's behaviour
    `[source: MediaBrowser.XbmcMetadata/Parsers/BaseNfoParser.cs:374-391 @ v10.11.11]`: a sidecar
    written by a newer server naming a lock this build does not have is not a broken sidecar, and
    refusing the whole element would throw away the locks that *are* understood.
    """
    if not text.strip():
        return None
    by_lowered = {member.value.lower(): member for member in MetadataField}
    found = [
        by_lowered[token.strip().lower()]
        for token in text.split("|")
        if token.strip().lower() in by_lowered
    ]
    return tuple(dict.fromkeys(found))


__all__ = [
    "BESIDE_THE_FILE",
    "DATE_FORMAT",
    "EARLIEST_YEAR",
    "FOLDER_SIDECAR",
    "MAX_BYTES",
    "NfoProblem",
    "NfoResult",
    "NfoWarning",
    "find_sidecar",
    "read_nfo",
]
