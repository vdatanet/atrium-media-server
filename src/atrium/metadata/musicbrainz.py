# SPDX-License-Identifier: GPL-3.0-or-later
"""MusicBrainz: the same contract as TMDB, a completely different budget.

**The unit of identification is the album, and that is the whole design.** MusicBrainz's public
etiquette is one request per second with an identifying `User-Agent`, and a naive per-track lookup
would turn a 5,000-track first scan into ninety minutes of waiting. So a release group is searched
for once per album, fetched once, and its artists are looked up once each - and **v1 never
searches per track**. A track's recording id comes from its own tags or not at all (spec section
3.5 rule 1, plan section 6.6).

The arithmetic that follows is the reason this module is shaped the way it is: an album of
fourteen tracks by one artist costs **three** requests, not seventeen.

**The `User-Agent` is not decoration.** MusicBrainz refuses traffic that does not identify itself,
so a contact address is this provider's credential even though it is not a secret - and its
absence disables the provider with a reason rather than producing a scan of rejected requests
(AC-9).

**No artwork.** The spec scopes MusicBrainz to names, dates and relationships; music art comes
from files and embedded covers. There is no download code path here at all, which is a stronger
statement than a disabled one.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from atrium.domain.items import ItemType
from atrium.metadata.model import (
    Ambiguous,
    Field,
    IdentifyResult,
    Identity,
    NoMatch,
    Subject,
)
from atrium.metadata.remote import DEFAULT_TTL, RemoteAccess

logger = logging.getLogger(__name__)

#: The `ProviderIds` key for a release group, which is what an album is identified as. Spelled the
#: way the reference spells it, and the way a sidecar and a Vorbis comment spell it.
NAME = "MusicBrainzReleaseGroup"

#: The other keys this module reads or writes.
ARTIST = "MusicBrainzArtist"
ALBUM = "MusicBrainzAlbum"
RECORDING = "MusicBrainzRecording"

#: **One request per second.** The published etiquette, and the number the album-level budget
#: exists to live within.
RATE = 1.0

BASE_URL = "https://musicbrainz.org/ws/2"

#: Two years is a wide tolerance, and deliberately so: a release group's first release date is the
#: *earliest* release anywhere, while a file's year is usually the pressing somebody owns.
YEAR_TOLERANCE = 2

_PUNCTUATION = re.compile(r"[^\w\s]", re.UNICODE)
_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class Budget:
    """What one refresh cost, so a test can assert the shape rather than the total.

    The property that matters is not "few requests" but **not one per track**, and a count that
    does not separate the two cannot say it.
    """

    searches: int = 0
    release_groups: int = 0
    artists: int = 0

    @property
    def total(self) -> int:
        return self.searches + self.release_groups + self.artists


class MusicBrainzProvider:
    """`RemoteProvider` for music, at album granularity."""

    name = NAME

    def __init__(self, access: RemoteAccess) -> None:
        self._access = access
        self._artists_seen: set[str] = set()

    def enabled(self) -> bool | str:
        """`True`, or the reason it is not (AC-9).

        MusicBrainz needs no key and **does** need a contact address: it refuses traffic that does
        not identify itself, so sending anonymous requests would be a scan of rejections rather
        than a scan.
        """
        if not self._access.credentials.contact:
            return (
                "no MusicBrainz contact is configured (providers.musicbrainz_contact); the "
                "service requires an identifying User-Agent"
            )
        return True

    # -- identification --------------------------------------------------------------------------

    def identify(self, subject: Subject) -> IdentifyResult:
        """Which release group this album is.

        **Only an album is identified.** A track is not searched for - its recording id comes from
        its own tags or not at all - and an artist is looked up by the id its album's credits
        carry rather than by name from scratch.
        """
        carried = subject.provider_ids.get(NAME) or subject.provider_ids.get(ALBUM)
        if carried:
            return Identity(provider=NAME, key=str(carried))

        if subject.kind is not ItemType.MUSIC_ALBUM:
            return NoMatch(
                f"MusicBrainz identifies albums; {subject.kind.value} takes its ids from its tags"
            )
        if not subject.name or not subject.name.strip():
            return NoMatch("nothing to search for: the album has no name")

        query = _query(subject)
        payload = self._access.get(
            "/release-group", params={"query": query, "fmt": "json"}, ttl=DEFAULT_TTL
        ).payload
        groups = payload.get("release-groups") if isinstance(payload, Mapping) else None
        if not isinstance(groups, list) or not groups:
            return NoMatch(f"MusicBrainz returned no candidates for {subject.name!r}")

        survivors = [one for one in groups if _matches(one, subject)]
        if len(survivors) == 1:
            return Identity(provider=NAME, key=str(survivors[0].get("id")))
        if not survivors:
            return NoMatch(
                f"MusicBrainz returned {len(groups)} candidate(s) for {subject.name!r}, none of "
                f"which matched on title and artist"
            )
        return Ambiguous(tuple(str(one.get("id")) for one in survivors))

    # -- fetching --------------------------------------------------------------------------------

    def fetch(self, identity: Identity) -> Mapping[Field, object]:
        """One release-group request: canonical title, date and artist credits."""
        payload = self._access.get(
            f"/release-group/{identity.key}",
            params={"inc": "artist-credits+genres", "fmt": "json"},
            ttl=None,
        ).payload
        if not isinstance(payload, Mapping):
            return {}

        values: dict[Field, object] = {}
        title = payload.get("title")
        if isinstance(title, str) and title.strip():
            values[Field.NAME] = title

        released = _first_release(payload)
        if released is not None:
            values[Field.PREMIERE_DATE] = datetime(
                released.year, released.month, released.day, tzinfo=UTC
            )
            values[Field.YEAR] = released.year

        credits_ = _artist_names(payload)
        if credits_:
            values[Field.ALBUM_ARTISTS] = credits_

        genres = [
            one["name"]
            for one in payload.get("genres", [])
            if isinstance(one, Mapping) and isinstance(one.get("name"), str)
        ]
        if genres:
            values[Field.GENRES] = genres

        ids: dict[str, str] = {NAME: identity.key}
        for entry in payload.get("artist-credit", []):
            artist = entry.get("artist") if isinstance(entry, Mapping) else None
            if isinstance(artist, Mapping) and isinstance(artist.get("id"), str):
                ids[ARTIST] = artist["id"]
                break
        values[Field.PROVIDER_IDS] = ids
        return values

    def fetch_artist(self, artist_id: str) -> Mapping[Field, object]:
        """One artist, by the id its album's credits carried.

        **Once each, not once per album.** An artist with forty albums is one request, because the
        cache answers the other thirty-nine - and an id never expires, so it is one request for
        the life of the install rather than one a fortnight.
        """
        self._artists_seen.add(artist_id)
        payload = self._access.get(f"/artist/{artist_id}", params={"fmt": "json"}, ttl=None).payload
        if not isinstance(payload, Mapping):
            return {}

        values: dict[Field, object] = {Field.PROVIDER_IDS: {ARTIST: artist_id}}
        name = payload.get("name")
        if isinstance(name, str) and name.strip():
            values[Field.NAME] = name
        sort_name = payload.get("sort-name")
        if isinstance(sort_name, str) and sort_name.strip():
            values[Field.SORT_NAME] = sort_name
        disambiguation = payload.get("disambiguation")
        if isinstance(disambiguation, str) and disambiguation.strip():
            values[Field.OVERVIEW] = disambiguation
        return values

    def recording_of(self, subject: Subject) -> str | None:
        """A track's recording id, **from its own tags and nowhere else**.

        No request is made here and none ever will be: a per-track lookup at one request per
        second is the ninety-minute first scan this module exists to avoid, and a track whose tags
        carry no id simply has none (plan section 6.6).
        """
        return subject.provider_ids.get(RECORDING) or subject.provider_ids.get("MusicBrainzTrack")


# ----------------------------------------------------------------------------------------------
# The match rule
# ----------------------------------------------------------------------------------------------


def _query(subject: Subject) -> str:
    """Lucene, as MusicBrainz's search wants it. Quoted, so a title with a colon is a title."""
    parts = [f'releasegroup:"{_escaped(subject.name or "")}"']
    if subject.album_artist:
        parts.append(f'artist:"{_escaped(subject.album_artist)}"')
    return " AND ".join(parts)


def _escaped(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _matches(candidate: Mapping[str, Any], subject: Subject) -> bool:
    """Title and, when the subject has one, artist. Same exactly-one rule as TMDB (§6.5)."""
    wanted = _normalise(subject.name or "")
    if not wanted or _normalise(str(candidate.get("title", ""))) != wanted:
        return False

    if subject.album_artist:
        credited = {_normalise(one) for one in _artist_names(candidate)}
        if _normalise(subject.album_artist) not in credited - {""}:
            return False

    released = _first_release(candidate)
    if subject.year is None or released is None:
        return True
    return abs(released.year - subject.year) <= YEAR_TOLERANCE


def _normalise(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text)
    stripped = "".join(one for one in decomposed if not unicodedata.combining(one))
    return _WHITESPACE.sub(" ", _PUNCTUATION.sub(" ", stripped)).strip().casefold()


def _artist_names(payload: Mapping[str, Any]) -> list[str]:
    """The credited artists, in credit order.

    MusicBrainz gives a credit as a list of parts with join phrases between them - `Artist A`,
    `" & "`, `Artist B` - and the names are what an album's artists are. The join phrases are
    display sugar; keeping them would put ` & ` in a list of artists.
    """
    names: list[str] = []
    for entry in payload.get("artist-credit", []):
        if not isinstance(entry, Mapping):
            continue
        artist = entry.get("artist")
        name = entry.get("name") or (artist.get("name") if isinstance(artist, Mapping) else None)
        if isinstance(name, str) and name.strip():
            names.append(name)
    return names


def _first_release(payload: Mapping[str, Any]) -> date | None:
    text = payload.get("first-release-date")
    if not isinstance(text, str):
        return None
    # MusicBrainz dates are as precise as it knows: `1998`, `1998-05`, `1998-05-04`. A year alone
    # is a year, not a date, so only the full form becomes one - and the partial forms still
    # supply the year through the caller's own `YEAR` mapping.
    parts = text.split("-")
    try:
        if len(parts) == 3:
            return date.fromisoformat(text)
        if len(parts) >= 1 and parts[0]:
            return date(int(parts[0]), 1, 1)
    except (ValueError, TypeError):
        return None
    return None


def user_agent(contact: str, version: str = "1.0") -> str:
    """The identifying header MusicBrainz requires, in the shape its documentation asks for."""
    return f"Atrium/{version} ( {contact} )"


__all__ = [
    "ALBUM",
    "ARTIST",
    "BASE_URL",
    "NAME",
    "RATE",
    "RECORDING",
    "YEAR_TOLERANCE",
    "Budget",
    "MusicBrainzProvider",
    "user_agent",
]
