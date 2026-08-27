# SPDX-License-Identifier: GPL-3.0-or-later
"""The vocabulary every metadata source, the merge and the write path share.

Pure: values in, values out. No file is opened here, no row is written, no request is made - which
is what lets the precedence matrix of plan section 6.1 be a table of plain values (plan section 3).

**Two vocabularies, and they are not the same size.** `Field` is what *this feature* merges, one
member per thing a provider can supply. `MetadataField` is what the reference **locks**, and it
has nine members to `Field`'s twenty-one. The two are related by `LOCK_OF`, which is partial in
both directions on purpose - see that mapping for the measurement behind it.

**Absence, emptiness and value-ness are three different things**, and the whole of section 3.1's
merge rule rests on keeping them apart:

* a key **absent** from a `FieldValues` means *this source has nothing to say about that field*;
* a key present with `None`, `""`, `[]` or whitespace is *present and empty*, which section 3.1
  says is **not a value** - the next provider in the chain still gets its turn;
* anything else is a value, `0` and `0.0` included.

The second rule is not the same as 003's seam, and confusing them would break that seam quietly.
`MetadataSource.tags_for` maps a tag name to a string, and there an empty string is a tag that is
**present and empty**, which the reference copies. `is_value` is about what may *set a field*, not
about what a file said.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass, field
from enum import StrEnum

from atrium.domain.items import ItemType


class Field(StrEnum):
    """One member per thing a provider can supply about an item.

    The values are internal. Nothing serialises them and nothing stores them: locks are stored as
    `MetadataField`, which is the reference's vocabulary and therefore the wire's.
    """

    NAME = "name"
    SORT_NAME = "sort_name"
    ORIGINAL_TITLE = "original_title"
    OVERVIEW = "overview"
    TAGLINE = "tagline"
    YEAR = "year"
    PREMIERE_DATE = "premiere_date"
    RUNTIME = "runtime"
    OFFICIAL_RATING = "official_rating"
    COMMUNITY_RATING = "community_rating"
    GENRES = "genres"
    STUDIOS = "studios"
    TAGS = "tags"
    PEOPLE = "people"
    ARTISTS = "artists"
    ALBUM_ARTISTS = "album_artists"
    INDEX_NUMBER = "index_number"
    PARENT_INDEX_NUMBER = "parent_index_number"
    PROVIDER_IDS = "provider_ids"
    NORMALIZATION_GAIN = "normalization_gain"
    IMAGES = "images"


class MetadataField(StrEnum):
    """The reference's lock vocabulary, spelled its way because it arrives and leaves spelled that
    way.

    Nine values `[spec: MetadataField]`. They reach an item through the sidecar - `<lockedfields>`
    carries them pipe-separated, parsed case-insensitively, and a token the enum does not know is
    **silently dropped** rather than refused
    `[source: MediaBrowser.XbmcMetadata/Parsers/BaseNfoParser.cs:374-391 @ v10.11.11]`. That is the
    only channel in v1: spec section 3.6 gives locks no HTTP route, so a lock is something a user
    wrote in a file.

    `PRODUCTION_LOCATIONS` is here because the enum has nine members and a `<lockedfields>` element
    may name it. Nothing in 004 resolves production locations, so locking them locks nothing -
    which is the honest shape, rather than dropping a member and turning a parsed token into an
    unparsed one.
    """

    CAST = "Cast"
    GENRES = "Genres"
    PRODUCTION_LOCATIONS = "ProductionLocations"
    STUDIOS = "Studios"
    TAGS = "Tags"
    NAME = "Name"
    OVERVIEW = "Overview"
    RUNTIME = "Runtime"
    OFFICIAL_RATING = "OfficialRating"


#: Which lock guards which field - **partial in both directions, and measured rather than
#: designed**.
#:
#: The reference's merge tests exactly one lock per guarded field and guards nothing else with it
#: `[source: MediaBrowser.Providers/Manager/MetadataService.cs:1009-1140 @ v10.11.11]`. Two
#: consequences are easy to get wrong by reasoning:
#:
#: * `Name` does **not** cover `SORT_NAME` or `ORIGINAL_TITLE`. The line immediately after the
#:   name lock overwrites the original title unconditionally, so a user who locks `Name` and then
#:   refreshes keeps their title and loses their original title. Grouping the three under one lock
#:   would be a kinder design and a divergence.
#: * Most fields cannot be locked at all. Tagline, year, premiere date, community rating, index
#:   numbers and provider ids have no lock in the reference, so a `Replace` overwrites them
#:   whatever the sidecar says.
#:
#: `MetadataField.PRODUCTION_LOCATIONS` appears in no row because 004 resolves no such field.
LOCK_OF: Mapping[Field, MetadataField] = {
    Field.NAME: MetadataField.NAME,
    Field.OVERVIEW: MetadataField.OVERVIEW,
    Field.RUNTIME: MetadataField.RUNTIME,
    Field.OFFICIAL_RATING: MetadataField.OFFICIAL_RATING,
    Field.GENRES: MetadataField.GENRES,
    Field.STUDIOS: MetadataField.STUDIOS,
    Field.TAGS: MetadataField.TAGS,
    Field.PEOPLE: MetadataField.CAST,
}

#: What a source found. An **absent key** says "nothing to say"; a key present with an empty value
#: says "present and empty", which section 3.1 says is not a value. `object` rather than a union
#: because the value's shape is the field's business: a string for a name, a list for genres, a
#: mapping for provider ids.
FieldValues = Mapping[Field, object]


class RefreshMode(StrEnum):
    """Spec section 3.6's three modes.

    The values are lowercase because they are read from and written to the configuration file, not
    to the wire: v1 has no refresh route, so nothing here is a reference spelling.
    """

    DEFAULT = "default"
    REPLACE = "replace"
    LOCAL_ONLY = "local-only"

    @property
    def consults_remote_providers(self) -> bool:
        return self is not RefreshMode.LOCAL_ONLY


def is_value(candidate: object) -> bool:
    """Whether `candidate` may set a field (spec section 3.1).

    `None`, an empty or whitespace-only string, and an empty collection are not values. Everything
    else is, **`0` and `0.0` included** - which is the reason this is a function and not a
    truthiness test. A community rating of zero is a rating somebody gave, and `if not value`
    would have thrown it away along with the empty strings.
    """
    if candidate is None:
        return False
    if isinstance(candidate, str):
        return bool(candidate.strip())
    if isinstance(candidate, bytes):
        return len(candidate) > 0
    if isinstance(candidate, (Sequence, Set, Mapping)):
        return len(candidate) > 0
    return True


def values_only(found: FieldValues) -> dict[Field, object]:
    """`found` with every present-but-empty entry dropped.

    A source may report what it looked for and did not find; the merge only ever sees what it may
    act on.
    """
    return {key: value for key, value in found.items() if is_value(value)}


@dataclass(frozen=True, slots=True)
class Subject:
    """Everything a remote provider is told about an item before it identifies it.

    Deliberately not the item. A provider gets what a search needs and nothing that would let it
    write - which is what keeps `metadata/` unable to reach the item table (architecture section 1)
    even by accident.
    """

    kind: ItemType
    name: str | None = None
    year: int | None = None
    provider_ids: Mapping[str, str] = field(default_factory=dict)
    album_artist: str | None = None
    """The album artist, for music. An album is identified by (artist, title) - plan section 6.6."""


@dataclass(frozen=True, slots=True)
class Identity:
    """The subject is this thing, in this provider's catalogue.

    `provider` is the `ProviderIds` key - `Tmdb`, `MusicBrainzReleaseGroup` - so an identity is
    exactly what gets stored, with no second naming scheme in between.
    """

    provider: str
    key: str


@dataclass(frozen=True, slots=True)
class NoMatch:
    """Nothing plausible came back. The item keeps whatever local metadata it has."""

    reason: str


@dataclass(frozen=True, slots=True)
class Ambiguous:
    """Several plausible candidates and no clear winner, so the item stays unidentified (AC-12).

    A separate result from `NoMatch` even though both leave the item alone, because the scan report
    counts them apart: nothing found is a library problem and several found is a naming problem,
    and telling a user which one they have is the difference between a fixable and an unfixable
    message.
    """

    candidates: tuple[str, ...]


#: What `RemoteProvider.identify` returns (plan section 5).
IdentifyResult = Identity | NoMatch | Ambiguous


__all__ = [
    "LOCK_OF",
    "Ambiguous",
    "Field",
    "FieldValues",
    "IdentifyResult",
    "Identity",
    "MetadataField",
    "NoMatch",
    "RefreshMode",
    "Subject",
    "is_value",
    "values_only",
]
