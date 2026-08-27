# SPDX-License-Identifier: GPL-3.0-or-later
"""TMDB: identify a film or a series, fetch what it knows, download bounded artwork.

Behind `metadata/remote.py`'s one door - this module constructs no client of its own, and a test
asserts that rather than trusting it (T11).

**The match rule is deliberately boring.** Normalise both sides, keep the candidates whose title
or original title equals the query and whose year, where both sides have one, differs by at most
one; **exactly one survivor is a match, zero is unidentified, and two or more is unidentified**
(spec section 3.5 rule 2, AC-12). No popularity weighting and no "top result": a rule with a knob
is a rule that guesses, and a wrong match is worse than a missing one because it is confidently
wrong, hard for a user to notice, and correctable only through a manual-identification flow v1
does not have.

**An identifier ends the argument.** A subject already carrying a TMDB id - from a sidecar, from a
previous refresh - is fetched directly and **no search request is made at all** (spec section 3.5
rule 1, AC-3). That single rule removes most wrong-match complaints, and it is why the sidecar's
`<uniqueid>` is treated as authoritative rather than as a hint.

**Artwork lands under the data directory** and is bounded: at most five files per item, 20 MB
each, and a refresh that finds an image already present by tag downloads nothing. Never inside a
library root - AC-15 is structural here, not a rule this module remembers.

> **On the response fixtures.** The recorded responses this module is tested against are
> **synthetic**, shaped after TMDB's documented API rather than captured from it: this repository
> has no TMDB key and its suite reaches no network. They pin the *parser*, which is what a
> regression would break. They do not pin the *API*, and plan section 8's opt-in live test is what
> would notice TMDB changing shape - which is exactly the division of labour that section
> describes.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from atrium.compat.ticks import from_timedelta
from atrium.domain.items import ItemType
from atrium.metadata.artwork import ImageAssociation, ImageKind, SourceKind, describe_bytes
from atrium.metadata.model import (
    Ambiguous,
    Field,
    IdentifyResult,
    Identity,
    NoMatch,
    PersonCredit,
    PersonKind,
    Subject,
)
from atrium.metadata.remote import DEFAULT_TTL, ProviderUnavailableError, RemoteAccess

logger = logging.getLogger(__name__)

#: The `ProviderIds` key. Also the identity's provider name, so what is searched for and what is
#: stored have one spelling between them.
NAME = "Tmdb"

#: Requests per second. The published courtesy limit, halved automatically on a `429` (T11).
RATE = 4.0

BASE_URL = "https://api.themoviedb.org/3"

#: Where a `file_path` from a TMDB payload is fetched from. `original` because 006 resizes from
#: whatever is stored and a poster fetched small can never be made large again.
IMAGE_BASE_URL = "https://image.tmdb.org/t/p/original"

#: Bounds on what one item may cost the data directory (plan section 6.5).
MAX_IMAGES_PER_ITEM = 5
MAX_IMAGE_BYTES = 20 * 1024 * 1024

#: How many backdrops are worth keeping. The reference's clients show one at a time and cycle;
#: three is enough for that and stops a film with two hundred backdrops from being one.
MAX_BACKDROPS = 3

#: A year in a payload's date differing from the subject's by more than this is a different film.
#: One, not zero: a release date and a filename's year disagree constantly across territories.
YEAR_TOLERANCE = 1

_PUNCTUATION = re.compile(r"[^\w\s]", re.UNICODE)
_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class RemoteImage:
    """One image a provider offered, before it is downloaded."""

    kind: ImageKind
    path: str


class TmdbProvider:
    """`RemoteProvider` for films and series (plan section 5).

    `access` is the one door; `artwork_root` is the directory downloads land in. Both are handed
    in, which is what lets a test exercise the whole module with a transport that answers from a
    dictionary and a temporary directory.
    """

    name = NAME

    def __init__(
        self,
        access: RemoteAccess,
        *,
        artwork_root: Path,
        country: str = "US",
    ) -> None:
        self._access = access
        self._artwork_root = artwork_root
        self._country = country.upper()

    # -- availability ----------------------------------------------------------------------------

    def handles(self, kind: ItemType) -> bool:
        """Films and series. A season or an episode takes its metadata from its series' payload,
        which v1 does not fetch (plan section 6.5 scopes episodes to the season payload, and no
        task in this feature builds that); a track is MusicBrainz's."""
        return kind in (ItemType.MOVIE, ItemType.SERIES)

    def enabled(self) -> bool | str:
        """`True`, or **the reason it is not** (AC-9).

        A string rather than a bare `False` because the scan report says which providers sat out
        and why, once per scan - an operator who has not configured a key should be told that
        rather than left wondering why nothing has a poster.
        """
        if not self._access.credentials.api_key:
            return "no TMDB API key is configured (providers.tmdb_api_key)"
        return True

    # -- identification --------------------------------------------------------------------------

    def identify(self, subject: Subject) -> IdentifyResult:
        """Which film or series this is, or why it could not be said.

        **A carried id short-circuits everything**: no request of any kind is made, not even a
        cached one, because there is nothing to ask.
        """
        carried = subject.provider_ids.get(NAME)
        if carried:
            return Identity(provider=NAME, key=str(carried))

        if not subject.name or not subject.name.strip():
            return NoMatch("nothing to search for: the item has no name")

        path, year_field = _search_for(subject.kind)
        if path is None:
            return NoMatch(f"TMDB does not identify {subject.kind.value} items")

        params = {"query": subject.name, "include_adult": "false"}
        if subject.year is not None:
            params[year_field] = str(subject.year)

        payload = self._get(path, params)
        results = payload.get("results") if isinstance(payload, Mapping) else None
        if not isinstance(results, list) or not results:
            return NoMatch(f"TMDB returned no candidates for {subject.name!r}")

        survivors = [one for one in results if _matches(one, subject)]
        if len(survivors) == 1:
            return Identity(provider=NAME, key=str(survivors[0].get("id")))
        if not survivors:
            return NoMatch(
                f"TMDB returned {len(results)} candidate(s) for {subject.name!r}, none of which "
                f"matched on title and year"
            )
        return Ambiguous(tuple(str(one.get("id")) for one in survivors))

    # -- fetching --------------------------------------------------------------------------------

    def fetch(self, identity: Identity, kind: ItemType) -> Mapping[Field, object]:
        """Everything TMDB knows about this id, in the field vocabulary.

        One request per identified item. Cached indefinitely rather than for a fortnight when it
        is looked up by id, because an id does not change meaning.
        """
        path = _fetch_path(kind, identity.key)
        if path is None:
            return {}
        payload = self._get(path, {"append_to_response": "credits,images,release_dates"})
        if not isinstance(payload, Mapping):
            return {}
        return self._values(payload, kind, identity)

    def images_for(self, identity: Identity, kind: ItemType) -> tuple[RemoteImage, ...]:
        """Which images TMDB offers, before anything is downloaded.

        Separate from `fetch` so a caller can decide *not* to download - which is what a refresh
        does when the item already has artwork with the same tags.
        """
        path = _fetch_path(kind, identity.key)
        if path is None:
            return ()
        payload = self._get(path, {"append_to_response": "credits,images,release_dates"})
        if not isinstance(payload, Mapping):
            return ()
        return _offered_images(payload)

    def download(
        self, item_id: str, offered: Sequence[RemoteImage], *, already: Iterable[str] = ()
    ) -> tuple[tuple[ImageAssociation, ...], tuple[str, ...]]:
        """Fetch the offered images into the data directory. Returns associations and warnings.

        Bounded three ways, and each bound is a real failure it prevents: **five files per item**
        (a film with two hundred backdrops is not two hundred downloads), **20 MB each** (a
        provider serving something enormous costs a warning, not a disc), and **nothing that is
        already present by tag** - so a re-refresh of an unchanged film downloads nothing at all.
        """
        known = set(already)
        associations: list[ImageAssociation] = []
        warnings: list[str] = []
        directory = self._artwork_root / item_id

        for image in offered[:MAX_IMAGES_PER_ITEM]:
            try:
                raw = self._bytes(image.path)
            except ProviderUnavailableError as exc:
                warnings.append(str(exc))
                continue
            if raw is None:
                continue
            if len(raw) > MAX_IMAGE_BYTES:
                warnings.append(
                    f"{NAME}: {image.path} is {len(raw) // (1024 * 1024)} MB, over the "
                    f"{MAX_IMAGE_BYTES // (1024 * 1024)} MB cap; not stored"
                )
                continue
            described = describe_bytes(raw)
            if described is None:
                warnings.append(f"{NAME}: {image.path} is not an image this build can identify")
                continue
            width, height, tag = described
            if tag in known:
                continue
            known.add(tag)

            index = sum(1 for one in associations if one.kind is image.kind)
            name = f"{image.kind.value.lower()}-{index}{Path(image.path).suffix or '.jpg'}"
            directory.mkdir(parents=True, exist_ok=True)
            (directory / name).write_bytes(raw)
            associations.append(
                ImageAssociation(
                    kind=image.kind,
                    index=index,
                    source_kind=SourceKind.REMOTE,
                    # Relative to the **data directory**, which is what `remote` means in that
                    # column - and the reason nothing here can name a path in a library root.
                    relative_path=f"metadata/artwork/{item_id}/{name}",
                    width=width,
                    height=height,
                    tag=tag,
                )
            )
        return tuple(associations), tuple(warnings)

    # -- plumbing --------------------------------------------------------------------------------

    def _get(self, path: str, params: Mapping[str, str]) -> Any:
        merged = {**params, "api_key": self._access.credentials.api_key}
        # **An identity looked up by id never expires; a search does.** An id does not change
        # meaning, so "what is TMDB 603" has the same answer next year - while a film that was not
        # in TMDB last month may be now, so a search that found nothing must be asked again.
        ttl = DEFAULT_TTL if path.startswith("/search/") else None
        return self._access.get(path, params=merged, ttl=ttl).payload

    def _bytes(self, file_path: str) -> bytes | None:
        """Image bytes, through the bucket and past the JSON cache (see `RemoteAccess`)."""
        return self._access.get_bytes(f"{IMAGE_BASE_URL}{file_path}", max_bytes=MAX_IMAGE_BYTES)

    def _values(
        self, payload: Mapping[str, Any], kind: ItemType, identity: Identity
    ) -> dict[Field, object]:
        values: dict[Field, object] = {}
        title = payload.get("title") or payload.get("name")
        if isinstance(title, str) and title.strip():
            values[Field.NAME] = title
        original = payload.get("original_title") or payload.get("original_name")
        if isinstance(original, str) and original.strip():
            values[Field.ORIGINAL_TITLE] = original
        for key, field_name in (("overview", Field.OVERVIEW), ("tagline", Field.TAGLINE)):
            text = payload.get(key)
            if isinstance(text, str) and text.strip():
                values[field_name] = text

        released = _date_of(payload)
        if released is not None:
            values[Field.PREMIERE_DATE] = datetime(
                released.year, released.month, released.day, tzinfo=UTC
            )
            values[Field.YEAR] = released.year

        rating = payload.get("vote_average")
        if isinstance(rating, (int, float)) and rating > 0:
            values[Field.COMMUNITY_RATING] = float(rating)

        runtime = payload.get("runtime")
        if isinstance(runtime, int) and runtime > 0:
            from datetime import timedelta

            values[Field.RUNTIME] = from_timedelta(timedelta(minutes=runtime))

        genres = [
            one["name"]
            for one in payload.get("genres", [])
            if isinstance(one, Mapping) and isinstance(one.get("name"), str)
        ]
        if genres:
            values[Field.GENRES] = genres

        studios = [
            one["name"]
            for one in payload.get("production_companies", [])
            if isinstance(one, Mapping) and isinstance(one.get("name"), str)
        ]
        if studios:
            values[Field.STUDIOS] = studios

        people = _people(payload)
        if people:
            values[Field.PEOPLE] = people

        certification = _certification(payload, self._country)
        if certification:
            values[Field.OFFICIAL_RATING] = certification

        ids: dict[str, str] = {NAME: identity.key}
        imdb = payload.get("imdb_id") or (payload.get("external_ids") or {}).get("imdb_id")
        if isinstance(imdb, str) and imdb.strip():
            ids["Imdb"] = imdb
        values[Field.PROVIDER_IDS] = ids

        _ = kind
        return values


# ----------------------------------------------------------------------------------------------
# The match rule
# ----------------------------------------------------------------------------------------------


def _matches(candidate: Mapping[str, Any], subject: Subject) -> bool:
    """One candidate against the subject, on title and year and nothing else.

    Both sides normalised the same way - case folded, diacritics stripped, punctuation removed,
    whitespace collapsed - so `WALL·E` and `Wall-E` are the same query and `The Matrix` is not
    `The Matrix Reloaded`.
    """
    wanted = _normalise(subject.name or "")
    if not wanted:
        return False
    titles = {
        _normalise(str(candidate.get(key, "")))
        for key in ("title", "original_title", "name", "original_name")
    }
    if wanted not in titles - {""}:
        return False

    released = _date_of(candidate)
    if subject.year is None or released is None:
        # Only one side has a year. The title matched exactly; refusing here would leave every
        # undated file unidentified, and the exactly-one rule still guards the ambiguous case.
        return True
    return abs(released.year - subject.year) <= YEAR_TOLERANCE


def _normalise(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text)
    stripped = "".join(one for one in decomposed if not unicodedata.combining(one))
    without_punctuation = _PUNCTUATION.sub(" ", stripped)
    return _WHITESPACE.sub(" ", without_punctuation).strip().casefold()


def _search_for(kind: ItemType) -> tuple[str | None, str]:
    if kind is ItemType.MOVIE:
        return "/search/movie", "year"
    if kind is ItemType.SERIES:
        return "/search/tv", "first_air_date_year"
    return None, ""


def _fetch_path(kind: ItemType, key: str) -> str | None:
    if kind is ItemType.MOVIE:
        return f"/movie/{key}"
    if kind is ItemType.SERIES:
        return f"/tv/{key}"
    return None


def _date_of(payload: Mapping[str, Any]) -> date | None:
    for key in ("release_date", "first_air_date"):
        text = payload.get(key)
        if isinstance(text, str) and len(text) == 10:
            try:
                return date.fromisoformat(text)
            except ValueError:
                continue
    return None


def _people(payload: Mapping[str, Any]) -> list[PersonCredit]:
    """Cast in billing order, then the crew jobs the field vocabulary has a kind for.

    Only directors, writers and composers: TMDB's crew runs to hundreds of entries per film, and
    an item carrying every gaffer is an item no client renders usefully.
    """
    credits_ = payload.get("credits")
    if not isinstance(credits_, Mapping):
        return []

    people: list[PersonCredit] = []
    cast = credits_.get("cast")
    if isinstance(cast, list):
        for entry in sorted(
            (one for one in cast if isinstance(one, Mapping)),
            key=lambda one: one.get("order", 10_000),
        ):
            name = entry.get("name")
            if isinstance(name, str) and name.strip():
                people.append(
                    PersonCredit(
                        name=name,
                        kind=PersonKind.ACTOR,
                        role=str(entry.get("character") or "") or None,
                        sort_order=entry.get("order")
                        if isinstance(entry.get("order"), int)
                        else None,
                    )
                )

    jobs = {
        "Director": PersonKind.DIRECTOR,
        "Writer": PersonKind.WRITER,
        "Screenplay": PersonKind.WRITER,
        "Original Music Composer": PersonKind.COMPOSER,
    }
    crew = credits_.get("crew")
    if isinstance(crew, list):
        for entry in crew:
            if not isinstance(entry, Mapping):
                continue
            kind = jobs.get(str(entry.get("job", "")))
            name = entry.get("name")
            if kind is not None and isinstance(name, str) and name.strip():
                people.append(PersonCredit(name=name, kind=kind))
    return people


def _certification(payload: Mapping[str, Any], country: str) -> str:
    """The configured country's certification, and no other.

    A film carries a rating in forty territories and they do not mean the same thing; picking one
    the operator did not choose would put `18` on a film an American client expects to see as `R`.
    """
    releases = payload.get("release_dates")
    if not isinstance(releases, Mapping):
        return ""
    for entry in releases.get("results", []):
        if not isinstance(entry, Mapping) or entry.get("iso_3166_1") != country:
            continue
        for release in entry.get("release_dates", []):
            certification = release.get("certification") if isinstance(release, Mapping) else None
            if isinstance(certification, str) and certification.strip():
                return certification
    return ""


def _offered_images(payload: Mapping[str, Any]) -> tuple[RemoteImage, ...]:
    """The selected poster, up to three backdrops, and the logo (plan section 6.5)."""
    images = payload.get("images")
    offered: list[RemoteImage] = []

    poster = payload.get("poster_path")
    if isinstance(poster, str) and poster:
        offered.append(RemoteImage(ImageKind.PRIMARY, poster))

    if isinstance(images, Mapping):
        for entry in list(images.get("backdrops", []))[:MAX_BACKDROPS]:
            path = entry.get("file_path") if isinstance(entry, Mapping) else None
            if isinstance(path, str) and path:
                offered.append(RemoteImage(ImageKind.BACKDROP, path))
        for entry in list(images.get("logos", []))[:1]:
            path = entry.get("file_path") if isinstance(entry, Mapping) else None
            if isinstance(path, str) and path:
                offered.append(RemoteImage(ImageKind.LOGO, path))

    if not any(one.kind is ImageKind.BACKDROP for one in offered):
        backdrop = payload.get("backdrop_path")
        if isinstance(backdrop, str) and backdrop:
            offered.append(RemoteImage(ImageKind.BACKDROP, backdrop))
    return tuple(offered)


__all__ = [
    "BASE_URL",
    "IMAGE_BASE_URL",
    "MAX_BACKDROPS",
    "MAX_IMAGES_PER_ITEM",
    "MAX_IMAGE_BYTES",
    "NAME",
    "RATE",
    "RemoteImage",
    "TmdbProvider",
]
