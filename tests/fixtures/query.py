# SPDX-License-Identifier: GPL-3.0-or-later
"""A known world, inserted through the repositories, for feature 005 to query.

**A seeded database, not a filesystem** (plan section 8). 003 already proved scanning; what 005
needs is a library whose contents are known exactly, so a query's answer can be compared against a
number rather than against whatever the fixture tree happens to hold. No scan runs here and no
file is read.

**Built through the repositories** rather than by inserting rows, which is what keeps the world
honest against schema drift: a shape the write path will not produce cannot be quietly relied on
by a test. The one exception is `item_user_data`, which has no repository until 007 owns it - the
rows are written through the ORM model, and the reason is named at `_seed_user_data` rather than
left to be inferred.

**Deterministic** (Principle VII). Every identifier is derived by `library/identity`, every date
is a constant, and nothing calls a clock: two builds of this world are byte-identical, which is
what lets a golden response be checked in.

The invariants are asserted in `tests/unit/test_query_fixture.py`, not here. A builder that
quietly stopped seeding the third series would otherwise weaken every test that depends on it and
fail none of them.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session as OrmSession

from atrium.db import models
from atrium.db.repositories import (
    ItemRepository,
    LibraryRepository,
    MetadataRepository,
    UserRepository,
)
from atrium.domain.items import CollectionType, Item, ItemType, MediaSource
from atrium.domain.library import Library
from atrium.domain.sorting import sort_name
from atrium.domain.user import LibraryAccess, User
from atrium.library import identity
from atrium.metadata.artwork import ImageAssociation, ImageKind, SourceKind
from atrium.metadata.merge import MetadataChanges
from atrium.metadata.model import Field, PersonCredit, PersonKind

# ------------------------------------------------------------------------------------------
# Constants: everything a clock or a random source would otherwise supply
# ------------------------------------------------------------------------------------------

#: One instant for the whole world. Item creation dates are offsets from it, so `DateCreated`
#: ordering is deliberate rather than an artefact of insertion speed.
EPOCH = datetime(2026, 1, 1, tzinfo=UTC)

#: Passed to every `MetadataRepository.apply` call. Without it `apply` stamps `utc_now()` and two
#: builds of this world differ in a column - which is a golden response that cannot be checked in.
REFRESHED_AT = datetime(2026, 2, 1, 12, 0, tzinfo=UTC)

MOVIES_LIBRARY_ID = "1" * 32
SHOWS_LIBRARY_ID = "2" * 32
MUSIC_LIBRARY_ID = "3" * 32

EVERYONE_ID = "a" * 32
RESTRICTED_ID = "b" * 32
NOBODY_ID = "c" * 32

#: Names that exist to break sorting, carried over from 003 (`tests/unit/test_sorting.py`).
#: **Two of them carry whitespace artefacts on purpose**: `Rock & Roll` sorts as `rock  roll` with
#: a double space and `S.W.A.T.` as `s w a t ` with a trailing one, because steps 3 to 5 of the
#: derivation neither trim nor collapse. A fixture that tidied them would make the ordering test
#: agree with a server that had tidied them too.
AWKWARD_NAMES = (
    "Rock & Roll",
    "S.W.A.T.",
    "The Matrix",
    "An Education",
    "A Film",
    "Amélie",
    "2 Fast 2 Furious",
    "10 Things I Hate About You",
)

#: How many films carry a `ProductionYear` and a `CommunityRating`, and where the years start.
#: Ten is enough for `years=[FIRST_YEAR]` to select one film and `min_community_rating` to select
#: a proper subset - both of which are what "the predicate narrows something" means.
RATED = 10
FIRST_YEAR = 1990

#: One hour, in ticks, on the film that also carries a resume position - `PlayedPercentage` is
#: position over runtime, and a world with positions and no runtimes could never emit one.
RUNTIME_TICKS = 36_000_000_000

#: The tags of the images this world carries, named so a DTO test asserts values rather than
#: presence. The first film keeps its original single Primary (tag `"d" * 32`, from T3).
SERIES_PRIMARY_TAG = "e" * 32
SERIES_THUMB_TAG = "f" * 32
SERIES_BACKDROP_TAGS = ("b1" * 16, "b2" * 16)
ALBUM_PRIMARY_TAG = "a1" * 16

#: The first episode of the first series carries a poster **of its own**, under a series that has
#: one too. 006 AC-14 says inheritance is unconditional - an episode gets its series' tags whether
#: or not it has artwork - and a world where no episode ever had any cannot tell that from an
#: emitter that simply falls back. 005 never needed the case; 006 T2 seeds it (006 tasks T2).
EPISODE_PRIMARY_TAG = "e1" * 16

#: Which of the rated films carries a real `PremiereDate`, and what it is. Older than the film's
#: own production year on purpose: see `_seed_movies`.
DATED_OFFSET = 1
DATED_PREMIERE = datetime(1989, 6, 1, tzinfo=UTC)

#: Total movies in the movies library, the awkward ones included. Plan section 8 row 4 pages this
#: at 1, 7 and 97, so the count is deliberately not a multiple of any of them.
CORPUS_SIZE = 100

#: One genre, two spellings, on two different films. They merge to a single by-name row
#: (behaviours section 2.18) while each item keeps the spelling its own source used.
GENRE_SPELLINGS = ("sci-fi", "Sci-Fi")

#: The compilation's album artist, which gets a `MusicArtist` item, and the per-track performers.
#: **`SOLO_PERFORMER` is nobody's album artist**, so its credit row carries a name and a null
#: `artist_item_id` - the revision-0004 shape, and the whole reason that column is nullable.
#:
#: **The third track is performed by the album artist**, which is what makes `artistIds` and
#: `albumArtistIds` distinguishable at all. With every performer being somebody else, filtering by
#: the artist's id under either parameter answers the same rows, and the credit column - the whole
#: of what separates `/Artists` from `/Artists/AlbumArtists` - is untested. A compilation with one
#: track by its own compiler is also the ordinary case rather than a contrivance.
ALBUM_ARTIST = "Various Artists"
TRACK_PERFORMERS = ("The Compilers", "Solo Performer", ALBUM_ARTIST)
SOLO_PERFORMER = "Solo Performer"

#: A **second** album artist, and a track on its record performed by the first one.
#:
#: This is what makes `artistIds` and `albumArtistIds` distinguishable, and the seeded world could
#: not do it before T6. Measured on the reference, `artistIds` is the superset - "Alan Cook"
#: answers 6 items to `albumArtistIds`' 2, and a performer who is nobody's album artist answers 2
#: to 0 `[probe: manual requests, Jellyfin 10.11.11, 2026-08-27]`. A world where every item's
#: performer and album artist are the same person makes the two parameters return identical rows,
#: and the credit column - the whole of what separates `/Artists` from `/Artists/AlbumArtists` -
#: goes untested while looking tested.
GUEST_ALBUM_ARTIST = "The Compilers"
GUEST_ALBUM = "Another Record"


@dataclass(frozen=True, slots=True)
class SeriesHandle:
    """One seeded series and everything a test needs to reach into it."""

    id: str
    name: str
    seasons: tuple[str, ...]
    episodes: tuple[str, ...]
    watched: str
    """The episode with a played user-data row. NextUp's answer for this series is the one after."""

    next_up: str
    """The episode NextUp must return: the lowest unwatched one after `watched`."""


@dataclass(frozen=True, slots=True)
class QueryWorld:
    """Handles into the seeded world. Every field is an identifier or a domain object."""

    movies: Library
    shows: Library
    music: Library

    everyone: User
    """Sees all three libraries."""

    restricted: User
    """Sees the movies library and nothing else."""

    nobody: User
    """Sees nothing at all - AC-9's user, whose `/UserViews` must be an empty envelope rather
    than an error."""

    corpus: tuple[str, ...]
    """Every movie id, in insertion order. `CORPUS_SIZE` of them."""

    awkward: tuple[str, ...]
    """The movie ids whose names are `AWKWARD_NAMES`, in the same order as that tuple."""

    rated: tuple[str, ...]
    """The films carrying a `ProductionYear` and a `CommunityRating`: `RATED` of them, years
    running from `FIRST_YEAR` and ratings from 5.0 in steps of 0.5."""

    series: tuple[SeriesHandle, ...]
    """Three of them. NextUp's one-row-per-series rule needs a choice among watched series to
    mean anything, which is why it is three and not one."""

    specials_season: str
    """The season-0 row on the second series. Season 0 sorts *last* (AC-11)."""

    multi_episode: str
    """The `S01E02-E03` episode on the second series: one item spanning two numbers."""

    imaged_episode: str
    """The first episode of the first series, which carries a `Primary` **of its own** under a
    series that has a poster and two backdrops. 006 AC-14's discriminating case: inheritance is
    unconditional, and an episode with no artwork anywhere cannot tell that from a fallback."""

    album: str
    """The compilation."""

    tracks: tuple[str, ...]
    album_artist: str
    """The `MusicArtist` item for `ALBUM_ARTIST`."""

    guest_artist: str
    """The `MusicArtist` item for `GUEST_ALBUM_ARTIST`, who owns a second album."""

    guest_track: str
    """A track on that second album **performed by** `ALBUM_ARTIST` and credited to
    `GUEST_ALBUM_ARTIST` as album artist. It is the one item that `artistIds` finds for the first
    artist and `albumArtistIds` does not."""

    favourites: tuple[str, ...]
    """Items with `is_favorite` set for `everyone`."""

    resumable: tuple[str, ...]
    """Items with a mid-playback position for `everyone`."""


# ------------------------------------------------------------------------------------------
# The builder
# ------------------------------------------------------------------------------------------


def build_query_world(session: OrmSession) -> QueryWorld:
    """Insert the whole world and return handles into it. Idempotent only on a fresh database."""
    libraries = LibraryRepository(session)
    users = UserRepository(session)
    items = ItemRepository(session)
    metadata = MetadataRepository(session)

    movies = libraries.add(
        Library(
            id=MOVIES_LIBRARY_ID,
            name="Films",
            collection_type=CollectionType.MOVIES,
            roots=("/libraries/films",),
        )
    )
    shows = libraries.add(
        Library(
            id=SHOWS_LIBRARY_ID,
            name="Shows",
            collection_type=CollectionType.TVSHOWS,
            roots=("/libraries/shows",),
        )
    )
    music = libraries.add(
        Library(
            id=MUSIC_LIBRARY_ID,
            name="Music",
            collection_type=CollectionType.MUSIC,
            roots=("/libraries/music",),
        )
    )

    everyone, restricted, nobody = _seed_users(users, movies)
    for library in (movies, shows, music):
        _add(items, _collection_folder(library))

    corpus, awkward = _seed_movies(items, metadata, movies)
    series, specials_season, multi_episode, imaged_episode = _seed_shows(items, metadata, shows)
    album, tracks, album_artist, guest_artist, guest_track = _seed_music(items, metadata, music)

    favourites = (corpus[0], album)
    resumable = (corpus[1], corpus[2])
    _seed_user_data(session, everyone, series, favourites, resumable)

    session.flush()
    return QueryWorld(
        movies=movies,
        shows=shows,
        music=music,
        everyone=everyone,
        restricted=restricted,
        nobody=nobody,
        corpus=corpus,
        awkward=awkward,
        rated=corpus[:RATED],
        series=series,
        specials_season=specials_season,
        multi_episode=multi_episode,
        imaged_episode=imaged_episode,
        album=album,
        tracks=tracks,
        album_artist=album_artist,
        guest_artist=guest_artist,
        guest_track=guest_track,
        favourites=favourites,
        resumable=resumable,
    )


# ------------------------------------------------------------------------------------------
# Users
# ------------------------------------------------------------------------------------------


def _seed_users(users: UserRepository, movies: Library) -> tuple[User, User, User]:
    """Three users, and the third is the one that matters.

    AC-9 is about a user who may see *nothing*: the answer is an empty envelope, not a `403` and
    not an error. That user is only reachable through a policy with `enable_all_folders` off and
    an empty allow-list, which is a shape nothing else in the suite builds.
    """
    everyone = users.add(User(id=EVERYONE_ID, name="everyone", enable_all_folders=True))
    restricted = users.add(User(id=RESTRICTED_ID, name="restricted", enable_all_folders=False))
    nobody = users.add(User(id=NOBODY_ID, name="nobody", enable_all_folders=False))
    users.set_library_access(restricted.id, LibraryAccess(enabled_folders=(movies.id,)))
    users.set_library_access(nobody.id, LibraryAccess(enabled_folders=()))
    return everyone, restricted, nobody


# ------------------------------------------------------------------------------------------
# Films
# ------------------------------------------------------------------------------------------


def _seed_movies(
    items: ItemRepository, metadata: MetadataRepository, library: Library
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """`CORPUS_SIZE` films, the first of them the awkward-named ones.

    One corpus, not two: a paging test that walked "the corpus" while the awkward names sat beside
    it in the same library would be paging a different set than it thought it was.
    """
    corpus: list[str] = []
    awkward: list[str] = []

    for index, name in enumerate(AWKWARD_NAMES):
        item_id = _add(items, _movie(library, name, index))
        corpus.append(item_id)
        awkward.append(item_id)

    for index in range(len(AWKWARD_NAMES), CORPUS_SIZE):
        # Zero-padded so the name order and the numeric order agree; a test comparing an ordering
        # against `sorted()` should not be measuring the padding instead.
        corpus.append(_add(items, _movie(library, f"Paging Item {index:03d}", index)))

    # **Years and ratings on the first ten films.** T3's list did not name them and T6 cannot
    # test `years` or `min_community_rating` without them: a predicate applied to a column that is
    # null on every row narrows nothing and passes every assertion about the rows it returned.
    for offset, item_id in enumerate(corpus[:RATED]):
        values: dict[Field, object] = {
            Field.YEAR: FIRST_YEAR + offset,
            Field.COMMUNITY_RATING: round(5.0 + offset * 0.5, 1),
        }
        if offset == DATED_OFFSET:
            # **One film with a real premiere date, and it is deliberately older than its own
            # production year.** Under `sortBy=PremiereDate` a year-only item sorts at January 1
            # of that year, so this film (1989) must come out *before* the one whose production
            # year is 1990 and which has no date at all. An implementation that clumped the
            # dateless - first or last, either way - puts them in the other order, and a fixture
            # whose dates agreed with its years could not tell the two apart.
            values[Field.PREMIERE_DATE] = DATED_PREMIERE
            # And a runtime, on the film that also carries a resume position, so
            # `PlayedPercentage` has both of its inputs on one item (T9).
            values[Field.RUNTIME] = RUNTIME_TICKS
        metadata.apply(item_id, MetadataChanges(values=values), refreshed_at=REFRESHED_AT)

    # One genre, two spellings, on two films. Both reach the same by-name row.
    for item_id, spelling in zip(corpus[:2], GENRE_SPELLINGS, strict=True):
        metadata.apply(
            item_id,
            MetadataChanges(values={Field.GENRES: [spelling]}),
            refreshed_at=REFRESHED_AT,
        )

    # Images on the first film only. **T3's list does not name them**; they are here because 004
    # owed 005 `ImageTags` emittable from `item_images` alone, and a world where every item has an
    # empty tag map cannot tell an emitter that works from one that returns `{}`.
    metadata.apply(
        corpus[0],
        MetadataChanges(
            values={
                Field.IMAGES: [
                    ImageAssociation(
                        kind=ImageKind.PRIMARY,
                        index=0,
                        source_kind=SourceKind.FILE,
                        relative_path="rock-and-roll/poster.jpg",
                        width=1000,
                        height=1500,
                        tag="d" * 32,
                    )
                ],
                Field.PEOPLE: [
                    PersonCredit(name="A Director", kind=PersonKind.DIRECTOR, sort_order=0),
                    PersonCredit(
                        name="An Actor", kind=PersonKind.ACTOR, role="Somebody", sort_order=1
                    ),
                ],
                Field.STUDIOS: ["A Studio"],
                # The gated scalars and maps, on the same film, so T9's absent-bare-present-asked
                # battery runs against an item that has a value for every one of them.
                Field.OVERVIEW: "A film about everything.",
                Field.TAGLINE: "One line about everything.",
                Field.ORIGINAL_TITLE: "Roc & Roll",
                Field.OFFICIAL_RATING: "PG",
                Field.TAGS: ["blue"],
                Field.PROVIDER_IDS: {"Imdb": "tt0000001", "Tmdb": "42"},
            }
        ),
        refreshed_at=REFRESHED_AT,
    )
    return tuple(corpus), tuple(awkward)


def _movie(library: Library, name: str, index: int) -> Item:
    relative = f"{index:03d} - {name}/{name}.mkv"
    return _with_sort_name(
        Item(
            id=identity.for_file(ItemType.MOVIE, library.id, relative),
            type=ItemType.MOVIE,
            name=name,
            library_id=library.id,
            parent_id=identity.for_library(library.id),
            sources=(MediaSource(relative_path=relative, size=1000 + index),),
            date_created=_created(index),
        )
    )


# ------------------------------------------------------------------------------------------
# Shows
# ------------------------------------------------------------------------------------------

#: (series name, seasons, whether it carries the specials and the multi-episode file).
SERIES_PLAN = (
    ("Alpha Show", (1, 2), False),
    ("Beta Show", (1,), True),
    ("Gamma Show", (1,), False),
)


def _seed_shows(
    items: ItemRepository, metadata: MetadataRepository, library: Library
) -> tuple[tuple[SeriesHandle, ...], str, str, str]:
    handles: list[SeriesHandle] = []
    specials_season = ""
    multi_episode = ""
    imaged_episode = ""

    for offset, (name, season_numbers, carries_the_odd_shapes) in enumerate(SERIES_PLAN):
        series_id = identity.for_name(ItemType.SERIES, library.id, name)
        _add(
            items,
            _with_sort_name(
                Item(
                    id=series_id,
                    type=ItemType.SERIES,
                    name=name,
                    library_id=library.id,
                    parent_id=identity.for_library(library.id),
                    date_created=_created(200 + offset),
                )
            ),
        )

        numbers = (*season_numbers, 0) if carries_the_odd_shapes else season_numbers
        seasons: list[str] = []
        episodes: list[str] = []

        for season_number in numbers:
            season_id = identity.for_season(series_id, season_number)
            seasons.append(season_id)
            _add(
                items,
                _with_sort_name(
                    Item(
                        id=season_id,
                        type=ItemType.SEASON,
                        # Season 0 is "Specials" everywhere a client renders it, and it sorts
                        # last rather than first despite its number (AC-11).
                        name="Specials" if season_number == 0 else f"Season {season_number}",
                        library_id=library.id,
                        parent_id=series_id,
                        index_number=season_number,
                        date_created=_created(200 + offset),
                    )
                ),
            )
            episodes.extend(
                _seed_episodes(
                    items, library, season_id, name, season_number, carries_the_odd_shapes
                )
            )
            if season_number == 0:
                specials_season = season_id

        if carries_the_odd_shapes:
            multi_episode = _episode_id(library, name, 1, 2)

        if offset == 0:
            # The first series carries a Primary, a Thumb and two Backdrops - and only the first,
            # so an emitter that resolves `SeriesPrimaryImageTag` or the `Parent*` walks can be
            # told apart from one that happens to find nothing everywhere (T9). An episode's row
            # reads all three kinds off its ancestors.
            metadata.apply(
                series_id,
                MetadataChanges(
                    values={
                        Field.IMAGES: [
                            ImageAssociation(
                                kind=ImageKind.PRIMARY,
                                index=0,
                                source_kind=SourceKind.FILE,
                                relative_path=f"{name}/poster.jpg",
                                width=680,
                                height=1000,
                                tag=SERIES_PRIMARY_TAG,
                            ),
                            ImageAssociation(
                                kind=ImageKind.THUMB,
                                index=0,
                                source_kind=SourceKind.FILE,
                                relative_path=f"{name}/landscape.jpg",
                                width=1280,
                                height=720,
                                tag=SERIES_THUMB_TAG,
                            ),
                            *(
                                ImageAssociation(
                                    kind=ImageKind.BACKDROP,
                                    index=backdrop_index,
                                    source_kind=SourceKind.FILE,
                                    relative_path=f"{name}/backdrop{backdrop_index}.jpg",
                                    width=1920,
                                    height=1080,
                                    tag=tag,
                                )
                                for backdrop_index, tag in enumerate(SERIES_BACKDROP_TAGS)
                            ),
                        ]
                    }
                ),
                refreshed_at=REFRESHED_AT,
            )
            # ...and its first episode carries one of its own. The discriminating fixture for
            # AC-14: the episode's row has `ImageTags.Primary` *and* the series' inherited tags
            # beside it, so an emitter that gated inheritance on the child having nothing would
            # fail here and nowhere else.
            imaged_episode = episodes[0]
            metadata.apply(
                imaged_episode,
                MetadataChanges(
                    values={
                        Field.IMAGES: [
                            ImageAssociation(
                                kind=ImageKind.PRIMARY,
                                index=0,
                                source_kind=SourceKind.FILE,
                                relative_path=f"{name}/Season 01/{name} S01E01.jpg",
                                width=1920,
                                height=1080,
                                tag=EPISODE_PRIMARY_TAG,
                            )
                        ]
                    }
                ),
                refreshed_at=REFRESHED_AT,
            )

        # Episode 1 of season 1 is watched, so NextUp has an answer for every series. Episode 2 of
        # season 1 is what it must answer with - and on the second series that is the
        # multi-episode file, which is the interesting case rather than an accident.
        handles.append(
            SeriesHandle(
                id=series_id,
                name=name,
                seasons=tuple(seasons),
                episodes=tuple(episodes),
                watched=_episode_id(library, name, 1, 1),
                next_up=_episode_id(library, name, 1, 2),
            )
        )
    return tuple(handles), specials_season, multi_episode, imaged_episode


def _seed_episodes(
    items: ItemRepository,
    library: Library,
    season_id: str,
    series_name: str,
    season_number: int,
    carries_the_odd_shapes: bool,
) -> list[str]:
    episodes: list[str] = []
    for episode_number in (1, 2, 4):
        # E02 on the odd series is `S01E02-E03`: one item that *is* both episodes rather than
        # standing for them (003 AC-5). E04 follows it, so the gap is visible either way.
        spans_to = (
            3 if carries_the_odd_shapes and season_number == 1 and episode_number == 2 else None
        )
        relative = _episode_path(series_name, season_number, episode_number, spans_to)
        item = _with_sort_name(
            Item(
                id=identity.for_file(ItemType.EPISODE, library.id, relative),
                type=ItemType.EPISODE,
                name=f"{series_name} S{season_number:02d}E{episode_number:02d}",
                library_id=library.id,
                parent_id=season_id,
                sources=(MediaSource(relative_path=relative, size=500),),
                index_number=episode_number,
                parent_index_number=season_number,
                end_index_number=spans_to,
                date_created=_created(300 + episode_number),
            )
        )
        _add(items, item)
        episodes.append(item.id)
    return episodes


def _episode_path(series_name: str, season: int, episode: int, spans_to: int | None = None) -> str:
    span = "" if spans_to is None else f"-E{spans_to:02d}"
    return f"{series_name}/Season {season:02d}/{series_name} S{season:02d}E{episode:02d}{span}.mkv"


def _episode_id(library: Library, series_name: str, season: int, episode: int) -> str:
    spans_to = 3 if series_name == "Beta Show" and season == 1 and episode == 2 else None
    return identity.for_file(
        ItemType.EPISODE, library.id, _episode_path(series_name, season, episode, spans_to)
    )


# ------------------------------------------------------------------------------------------
# Music
# ------------------------------------------------------------------------------------------


def _seed_music(
    items: ItemRepository, metadata: MetadataRepository, library: Library
) -> tuple[str, tuple[str, ...], str, str, str]:
    """A compilation: one album artist, a different performer on every track.

    That shape is what makes it *one* album rather than one per track, and it is the reason
    `item_artists.credit` exists. One of the performers is nobody's album artist, so its credit
    row has a name and a null `artist_item_id` - the revision-0004 shape.
    """
    artist_id = identity.for_name(ItemType.MUSIC_ARTIST, library.id, ALBUM_ARTIST)
    _add(
        items,
        _with_sort_name(
            Item(
                id=artist_id,
                type=ItemType.MUSIC_ARTIST,
                name=ALBUM_ARTIST,
                library_id=library.id,
                parent_id=identity.for_library(library.id),
                date_created=_created(400),
            )
        ),
    )

    album_name = "A Compilation"
    album_id = identity.for_name(ItemType.MUSIC_ALBUM, library.id, album_name)
    _add(
        items,
        _with_sort_name(
            Item(
                id=album_id,
                type=ItemType.MUSIC_ALBUM,
                name=album_name,
                library_id=library.id,
                parent_id=artist_id,
                date_created=_created(401),
            )
        ),
    )
    metadata.apply(
        album_id,
        MetadataChanges(
            values={
                Field.ALBUM_ARTISTS: [ALBUM_ARTIST],
                Field.GENRES: [GENRE_SPELLINGS[0]],
                # A cover, so a track's `AlbumPrimaryImageTag` has something to point at (T9).
                Field.IMAGES: [
                    ImageAssociation(
                        kind=ImageKind.PRIMARY,
                        index=0,
                        source_kind=SourceKind.FILE,
                        relative_path=f"{ALBUM_ARTIST}/{album_name}/cover.jpg",
                        width=1000,
                        height=1000,
                        tag=ALBUM_PRIMARY_TAG,
                    )
                ],
            }
        ),
        refreshed_at=REFRESHED_AT,
    )

    guest_artist_id, guest_track = _seed_guest_album(items, metadata, library)

    tracks: list[str] = []
    for number, performer in enumerate(TRACK_PERFORMERS, start=1):
        relative = f"{ALBUM_ARTIST}/{album_name}/{number:02d} Track {number}.flac"
        track = _with_sort_name(
            Item(
                id=identity.for_file(ItemType.AUDIO, library.id, relative),
                type=ItemType.AUDIO,
                name=f"Track {number}",
                library_id=library.id,
                parent_id=album_id,
                sources=(MediaSource(relative_path=relative, size=300),),
                index_number=number,
                parent_index_number=1,
                date_created=_created(410 + number),
            )
        )
        _add(items, track)
        metadata.apply(
            track.id,
            MetadataChanges(
                values={Field.ARTISTS: [performer], Field.ALBUM_ARTISTS: [ALBUM_ARTIST]}
            ),
            refreshed_at=REFRESHED_AT,
        )
        tracks.append(track.id)
    return album_id, tuple(tracks), artist_id, guest_artist_id, guest_track


def _seed_guest_album(
    items: ItemRepository, metadata: MetadataRepository, library: Library
) -> tuple[str, str]:
    """A second artist, a second album, and one track on it performed by the first artist.

    A guest appearance, which is an ordinary thing for a record to have and the only shape in
    which the two artist parameters can disagree: the track's *performer* is one artist and its
    *album artist* is another, so exactly one of the two filters finds it.
    """
    artist_id = identity.for_name(ItemType.MUSIC_ARTIST, library.id, GUEST_ALBUM_ARTIST)
    _add(
        items,
        _with_sort_name(
            Item(
                id=artist_id,
                type=ItemType.MUSIC_ARTIST,
                name=GUEST_ALBUM_ARTIST,
                library_id=library.id,
                parent_id=identity.for_library(library.id),
                date_created=_created(420),
            )
        ),
    )
    album_id = identity.for_name(ItemType.MUSIC_ALBUM, library.id, GUEST_ALBUM)
    _add(
        items,
        _with_sort_name(
            Item(
                id=album_id,
                type=ItemType.MUSIC_ALBUM,
                name=GUEST_ALBUM,
                library_id=library.id,
                parent_id=artist_id,
                date_created=_created(421),
            )
        ),
    )
    metadata.apply(
        album_id,
        MetadataChanges(values={Field.ALBUM_ARTISTS: [GUEST_ALBUM_ARTIST]}),
        refreshed_at=REFRESHED_AT,
    )

    relative = f"{GUEST_ALBUM_ARTIST}/{GUEST_ALBUM}/01 Guest Track.flac"
    track = _with_sort_name(
        Item(
            id=identity.for_file(ItemType.AUDIO, library.id, relative),
            type=ItemType.AUDIO,
            name="Guest Track",
            library_id=library.id,
            parent_id=album_id,
            sources=(MediaSource(relative_path=relative, size=300),),
            index_number=1,
            parent_index_number=1,
            date_created=_created(422),
        )
    )
    _add(items, track)
    metadata.apply(
        track.id,
        MetadataChanges(
            values={Field.ARTISTS: [ALBUM_ARTIST], Field.ALBUM_ARTISTS: [GUEST_ALBUM_ARTIST]}
        ),
        refreshed_at=REFRESHED_AT,
    )
    return artist_id, track.id


# ------------------------------------------------------------------------------------------
# User data
# ------------------------------------------------------------------------------------------


def _seed_user_data(
    session: OrmSession,
    user: User,
    series: tuple[SeriesHandle, ...],
    favourites: tuple[str, ...],
    resumable: tuple[str, ...],
) -> None:
    """The one part of this world written as rows rather than through a repository.

    `item_user_data` has no repository: 007 owns what these columns mean and has not been built.
    Writing the model directly is the honest alternative to inventing a write path this feature
    does not own - and the rows are keyed on `item_key`, the **derived identity**, which is the
    column's whole design (003 spec section 3.8): user data outlives the item row.
    """
    for handle in series:
        session.add(
            models.ItemUserData(
                user_id=user.id,
                item_key=handle.watched,
                played=True,
                play_count=1,
                last_played_date=datetime(2026, 3, 1, tzinfo=UTC),
            )
        )
    for item_key in favourites:
        session.add(models.ItemUserData(user_id=user.id, item_key=item_key, is_favorite=True))
    for offset, item_key in enumerate(resumable):
        session.add(
            models.ItemUserData(
                user_id=user.id,
                item_key=item_key,
                # Mid-playback: far enough in to count as resumable under any threshold 007
                # settles on, and far enough from the end not to count as played.
                playback_position_ticks=(600 + offset) * 10_000_000,
                last_played_date=datetime(2026, 3, 2, tzinfo=UTC),
            )
        )
    session.flush()


# ------------------------------------------------------------------------------------------
# Small helpers
# ------------------------------------------------------------------------------------------


def _collection_folder(library: Library) -> Item:
    return _with_sort_name(
        Item(
            id=identity.for_library(library.id),
            type=ItemType.COLLECTION_FOLDER,
            name=library.name,
            library_id=library.id,
            date_created=EPOCH,
        )
    )


def _with_sort_name(item: Item) -> Item:
    """The real derivation, not a copy of the name.

    `ItemRepository.add` writes whatever `sort_name` the item carries, so a fixture that set it to
    the name would seed a world ordered by a rule the server does not use - and every ordering
    test would then agree with itself.
    """
    return replace(item, sort_name=sort_name(item))


def _add(items: ItemRepository, item: Item) -> str:
    items.add(item)
    return item.id


def _created(offset: int) -> datetime:
    """A distinct, ordered creation date per item, with no clock involved."""
    return EPOCH + timedelta(seconds=offset)
