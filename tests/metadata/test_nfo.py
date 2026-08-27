# SPDX-License-Identifier: GPL-3.0-or-later
"""Sidecars: what the fixtures parse to, and what the dangerous ones do instead.

The fixtures are the ones T2 checked in, described in `tests/fixtures/metadata/README.md`. Three
of them exist for a single sentence in the plan that turned out to be false - stdlib
`ElementTree` does not refuse document type declarations - and one exists for a sentence in the
plan that is still false in the other direction: a `<genre>` containing a slash **is** split by
the reference, so `movie-full.nfo` carries one and this suite asserts two genres come out.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from atrium.compat.ticks import to_seconds
from atrium.domain.items import ItemType
from atrium.metadata.model import Field, MetadataField, PersonKind
from atrium.metadata.nfo import (
    MAX_BYTES,
    NfoProblem,
    find_sidecar,
    read_nfo,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "metadata" / "nfo"


def values_of(name: str, kind: ItemType = ItemType.MOVIE) -> dict[Field, object]:
    result = read_nfo(FIXTURES / name, kind)
    assert not result.warnings, f"{name} warned: {[str(w) for w in result.warnings]}"
    return dict(result.values)


# ----------------------------------------------------------------------------------------------
# AC-1: a full sidecar resolves a film entirely
# ----------------------------------------------------------------------------------------------


def test_a_full_sidecar_yields_every_scalar_field() -> None:
    found = values_of("movie-full.nfo")
    assert found[Field.NAME] == "The Fixture"
    assert found[Field.SORT_NAME] == "Fixture, The"
    assert found[Field.ORIGINAL_TITLE] == "El Atrezzo"
    assert found[Field.YEAR] == 1999
    assert found[Field.PREMIERE_DATE] == datetime(1999, 4, 23, tzinfo=UTC)
    assert found[Field.OVERVIEW] == "A film that exists so a parser has something to read."
    assert found[Field.TAGLINE] == "Every field, once."
    assert found[Field.OFFICIAL_RATING] == "PG-13"
    assert found[Field.COMMUNITY_RATING] == pytest.approx(7.4)


def test_runtime_is_ticks_converted_once_at_ingestion() -> None:
    """Minutes in the file, ticks in the vocabulary, and the conversion happens here (architecture
    section 4). 97 minutes is 5,820 seconds; anything else means two conversions or none."""
    assert to_seconds(int(values_of("movie-full.nfo")[Field.RUNTIME])) == pytest.approx(97 * 60)


def test_the_lists_keep_their_document_order() -> None:
    found = values_of("movie-full.nfo")
    assert found[Field.STUDIOS] == ["Fixture Pictures", "Second Studio"]
    assert found[Field.TAGS] == ["synthetic", "checked-in"]


def test_the_cast_keeps_its_billing_order_and_its_roles() -> None:
    """Spec section 3.7 rule 2: clients render "starring" from the first few entries, so an order
    that is an accident of insertion is a different cast list."""
    people = values_of("movie-full.nfo")[Field.PEOPLE]
    assert isinstance(people, list)
    actors = [person for person in people if person.kind is PersonKind.ACTOR]
    assert [person.name for person in actors] == ["First Billed", "Second Billed", "Third Billed"]
    assert [person.role for person in actors] == ["The Lead", "The Other One", "Uncredited"]


def test_directors_and_writers_are_people_too() -> None:
    people = values_of("movie-full.nfo")[Field.PEOPLE]
    assert isinstance(people, list)
    by_kind = {person.kind: person.name for person in people if person.kind is not PersonKind.ACTOR}
    assert by_kind == {PersonKind.DIRECTOR: "A Director", PersonKind.WRITER: "A Writer"}


# ----------------------------------------------------------------------------------------------
# The genre split, which the plan had backwards
# ----------------------------------------------------------------------------------------------


def test_a_genre_containing_a_slash_is_split() -> None:
    """[Plan §6.2] said it is not, and cited the reference's parser. The reference's parser splits
    on a bare `/` and trims each part
    `[source: MediaBrowser.XbmcMetadata/Parsers/BaseNfoParser.cs:566-583 @ v10.11.11]`.

    Not splitting would give Atrium a genre - `Science Fiction / Fantasy` - that no reference
    server has, on a file both of them read.
    """
    assert values_of("movie-full.nfo")[Field.GENRES] == ["Drama", "Science Fiction", "Fantasy"]


@pytest.mark.parametrize(
    ("written", "expected"),
    [
        ("Drama", ["Drama"]),
        ("Drama / Romance", ["Drama", "Romance"]),
        ("Drama/Romance", ["Drama", "Romance"]),
        # The cost of the rule, and it is the reference's to own rather than ours to fix.
        ("Rock/Pop", ["Rock", "Pop"]),
        ("", []),
        ("/", []),
        ("Drama //  Romance ", ["Drama", "Romance"]),
    ],
)
def test_the_split_rule_end_to_end(tmp_path: Path, written: str, expected: list[str]) -> None:
    sidecar = tmp_path / "movie.nfo"
    sidecar.write_text(f"<movie><genre>{written}</genre></movie>", encoding="utf-8")
    assert read_nfo(sidecar, ItemType.MOVIE).values.get(Field.GENRES, []) == expected


# ----------------------------------------------------------------------------------------------
# AC-2: a sparse sidecar leaves the rest to the next provider
# ----------------------------------------------------------------------------------------------


def test_a_sparse_sidecar_says_nothing_about_what_it_leaves_empty() -> None:
    """`<plot></plot>` and a whitespace-only `<tagline>` are *present and empty*, which spec
    section 3.1 says is not a value - so the key is absent and the next provider gets its turn.
    Recording them as empty strings would erase everything below them in the chain.
    """
    found = values_of("movie-sparse.nfo")
    assert found == {Field.NAME: "The Sparse Fixture", Field.YEAR: 2001}
    assert Field.OVERVIEW not in found
    assert Field.TAGLINE not in found


# ----------------------------------------------------------------------------------------------
# AC-3: an id-bearing sidecar
# ----------------------------------------------------------------------------------------------


def test_provider_ids_come_from_both_spellings() -> None:
    """`<uniqueid type="tmdb">` is the modern one; `<imdbid>` reaches the reference through its
    parser's default branch, matching `<Key>Id` case-insensitively."""
    assert values_of("movie-ids.nfo")[Field.PROVIDER_IDS] == {"Tmdb": "33333", "Imdb": "tt4444444"}


def test_the_id_bearing_sidecar_says_nothing_else() -> None:
    """AC-3 is about identification being skipped, so what matters is that the ids arrive without
    the sidecar having to carry a title for them to be trusted."""
    found = values_of("movie-ids.nfo")
    assert set(found) == {Field.PROVIDER_IDS}


def test_the_default_attribute_is_not_consulted(tmp_path: Path) -> None:
    """Every `uniqueid` is stored. Which one a matcher prefers is spec section 3.5 rule 1's
    business - whichever id the provider being asked recognises - not this parser's."""
    sidecar = tmp_path / "movie.nfo"
    sidecar.write_text(
        '<movie><uniqueid type="tmdb" default="false">1</uniqueid>'
        '<uniqueid type="imdb" default="true">tt2</uniqueid></movie>',
        encoding="utf-8",
    )
    assert read_nfo(sidecar, ItemType.MOVIE).values[Field.PROVIDER_IDS] == {
        "Tmdb": "1",
        "Imdb": "tt2",
    }


def test_kodis_older_id_element(tmp_path: Path) -> None:
    """`<id TMDB="…" IMDB="…">tt…</id>`, and the content is read as an IMDb id **only** when it
    starts with `tt` - Kodi's documentation says the content is arbitrary."""
    sidecar = tmp_path / "movie.nfo"
    sidecar.write_text('<movie><id TMDB="7">tt9</id></movie>', encoding="utf-8")
    assert read_nfo(sidecar, ItemType.MOVIE).values[Field.PROVIDER_IDS] == {
        "Tmdb": "7",
        "Imdb": "tt9",
    }

    other = tmp_path / "other.nfo"
    other.write_text("<movie><id>whatever kodi wrote</id></movie>", encoding="utf-8")
    assert Field.PROVIDER_IDS not in read_nfo(other, ItemType.MOVIE).values


def test_a_provider_nobody_here_knows_is_kept_as_written(tmp_path: Path) -> None:
    """It is still the user's decision about what this film is, and discarding it would make the
    next refresh guess (spec section 3.2)."""
    sidecar = tmp_path / "movie.nfo"
    sidecar.write_text('<movie><uniqueid type="anidb">42</uniqueid></movie>', encoding="utf-8")
    assert read_nfo(sidecar, ItemType.MOVIE).values[Field.PROVIDER_IDS] == {"anidb": "42"}


def test_musicbrainz_ids_reach_their_canonical_spellings() -> None:
    assert values_of("album.nfo", ItemType.MUSIC_ALBUM)[Field.PROVIDER_IDS] == {
        "MusicBrainzAlbum": "00000000-0000-4000-8000-000000000001",
        "MusicBrainzReleaseGroup": "00000000-0000-4000-8000-000000000002",
    }
    assert values_of("artist.nfo", ItemType.MUSIC_ARTIST)[Field.PROVIDER_IDS] == {
        "MusicBrainzArtist": "00000000-0000-4000-8000-000000000003"
    }


# ----------------------------------------------------------------------------------------------
# AC-4: a malformed sidecar warns, naming the file, and nothing else
# ----------------------------------------------------------------------------------------------


def test_a_malformed_sidecar_warns_and_yields_nothing() -> None:
    result = read_nfo(FIXTURES / "movie-malformed.nfo", ItemType.MOVIE)
    assert dict(result.values) == {}
    assert len(result.warnings) == 1
    assert result.warnings[0].problem is NfoProblem.MALFORMED
    assert result.warnings[0].path.name == "movie-malformed.nfo"
    assert "movie-malformed.nfo" in str(result.warnings[0])


@pytest.mark.parametrize(
    "name",
    ["movie-entity-internal.nfo", "movie-entity-external.nfo", "movie-entity-bomb.nfo"],
)
def test_all_three_entity_shapes_land_on_the_same_path(name: str) -> None:
    """The three the stdlib treats three different ways - expand, raise, expand enormously - all
    become one warning here, because the declaration is refused before any of it happens."""
    result = read_nfo(FIXTURES / name, ItemType.MOVIE)
    assert dict(result.values) == {}
    assert [warning.problem for warning in result.warnings] == [NfoProblem.HAS_A_DOCUMENT_TYPE]
    assert result.warnings[0].path.name == name


def test_the_expansion_bomb_is_refused_before_it_expands() -> None:
    """400 bytes that the stdlib parser turns into 200,000 characters. The point is not that the
    warning arrives - it is that nothing allocated the string first."""
    raw = (FIXTURES / "movie-entity-bomb.nfo").read_bytes()
    assert len(raw) < 1000, "the fixture is small; the danger is what it expands to"
    result = read_nfo(FIXTURES / "movie-entity-bomb.nfo", ItemType.MOVIE)
    assert dict(result.values) == {}


def test_a_sidecar_over_the_cap_is_not_parsed(tmp_path: Path) -> None:
    """No fixture for this, on purpose: a file over the cap is megabytes and the fixture tree is
    twenty kilobytes."""
    oversized = tmp_path / "movie.nfo"
    oversized.write_bytes(b"<movie><title>x</title></movie>" + b" " * MAX_BYTES)
    result = read_nfo(oversized, ItemType.MOVIE)
    assert dict(result.values) == {}
    assert result.warnings[0].problem is NfoProblem.TOO_LARGE


def test_a_missing_sidecar_warns_rather_than_raising(tmp_path: Path) -> None:
    result = read_nfo(tmp_path / "absent.nfo", ItemType.MOVIE)
    assert result.warnings[0].problem is NfoProblem.UNREADABLE


# ----------------------------------------------------------------------------------------------
# Locks - the only channel by which one reaches an item in v1
# ----------------------------------------------------------------------------------------------


def test_a_sidecar_carries_no_locks_unless_it_says_so() -> None:
    result = read_nfo(FIXTURES / "movie-full.nfo", ItemType.MOVIE)
    assert result.is_locked is None
    assert result.locked_fields is None


def test_lockdata_and_lockedfields_are_read(tmp_path: Path) -> None:
    sidecar = tmp_path / "movie.nfo"
    sidecar.write_text(
        "<movie><lockdata>true</lockdata><lockedfields>Name|Genres|Cast</lockedfields></movie>",
        encoding="utf-8",
    )
    result = read_nfo(sidecar, ItemType.MOVIE)
    assert result.is_locked is True
    assert result.locked_fields == (MetadataField.NAME, MetadataField.GENRES, MetadataField.CAST)


def test_an_unknown_lock_token_is_dropped_and_the_rest_survive(tmp_path: Path) -> None:
    """The reference's behaviour: a sidecar written by a newer server naming a lock this build
    does not have is not a broken sidecar, and refusing the element would throw away the locks
    that *are* understood."""
    sidecar = tmp_path / "movie.nfo"
    sidecar.write_text(
        "<movie><lockedfields>Name|Sparkle|genres</lockedfields></movie>", encoding="utf-8"
    )
    assert read_nfo(sidecar, ItemType.MOVIE).locked_fields == (
        MetadataField.NAME,
        MetadataField.GENRES,
    )


# ----------------------------------------------------------------------------------------------
# The measured leniencies, each of which a reasonable implementation would get wrong
# ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("written", "expected"),
    [("97", 97), ("97 min", 97), ("97 minutes", 97), ("", None), ("about an hour", None)],
)
def test_runtime_reads_the_text_before_the_first_space(
    tmp_path: Path, written: str, expected: int | None
) -> None:
    sidecar = tmp_path / "movie.nfo"
    sidecar.write_text(f"<movie><runtime>{written}</runtime></movie>", encoding="utf-8")
    found = read_nfo(sidecar, ItemType.MOVIE).values.get(Field.RUNTIME)
    if expected is None:
        assert found is None
    else:
        assert to_seconds(int(found)) == pytest.approx(expected * 60)


@pytest.mark.parametrize(("written", "expected"), [("7,4", 7.4), ("7.4", 7.4), ("bad", None)])
def test_a_comma_is_a_decimal_point_in_a_rating(
    tmp_path: Path, written: str, expected: float | None
) -> None:
    """Half of Europe writes `7,4`, and the reference replaces the comma before parsing."""
    sidecar = tmp_path / "movie.nfo"
    sidecar.write_text(f"<movie><rating>{written}</rating></movie>", encoding="utf-8")
    found = read_nfo(sidecar, ItemType.MOVIE).values.get(Field.COMMUNITY_RATING)
    assert found is None if expected is None else found == pytest.approx(expected)


@pytest.mark.parametrize(("written", "expected"), [("1999", 1999), ("1850", None), ("0", None)])
def test_a_year_at_or_below_1850_is_ignored(
    tmp_path: Path, written: str, expected: int | None
) -> None:
    """The reference's guard, and the effect is what matters: `<year>0</year>`, which generators
    write for "unknown", leaves the year to the next provider instead of filing a film under it."""
    sidecar = tmp_path / "movie.nfo"
    sidecar.write_text(f"<movie><year>{written}</year></movie>", encoding="utf-8")
    assert read_nfo(sidecar, ItemType.MOVIE).values.get(Field.YEAR) == expected


def test_a_premiere_date_supplies_the_year_when_nothing_else_did(tmp_path: Path) -> None:
    sidecar = tmp_path / "movie.nfo"
    sidecar.write_text("<movie><premiered>1999-04-23</premiered></movie>", encoding="utf-8")
    found = read_nfo(sidecar, ItemType.MOVIE).values
    assert found[Field.PREMIERE_DATE] == datetime(1999, 4, 23, tzinfo=UTC), (
        "midnight UTC, not a bare date: PremiereDate is a date-time on the wire"
    )
    assert found[Field.YEAR] == 1999


def test_an_explicit_year_wins_over_the_premiere_dates(tmp_path: Path) -> None:
    """`ProductionYear ??= releaseDate.Year` - the date fills the year, it does not overwrite it,
    even when the two disagree."""
    sidecar = tmp_path / "movie.nfo"
    sidecar.write_text(
        "<movie><year>1998</year><premiered>1999-04-23</premiered></movie>", encoding="utf-8"
    )
    assert read_nfo(sidecar, ItemType.MOVIE).values[Field.YEAR] == 1998


@pytest.mark.parametrize("written", ["23-04-1999", "1999", "19990423", "1999-W17-5", "not a date"])
def test_a_date_in_any_other_format_is_left_to_the_next_provider(
    tmp_path: Path, written: str
) -> None:
    """The reference parses one format exactly. `date.fromisoformat` accepts several more, so the
    two would disagree on the same file without the shape check."""
    sidecar = tmp_path / "movie.nfo"
    sidecar.write_text(f"<movie><premiered>{written}</premiered></movie>", encoding="utf-8")
    assert Field.PREMIERE_DATE not in read_nfo(sidecar, ItemType.MOVIE).values


@pytest.mark.parametrize(
    ("written", "expected"),
    [
        ("A Director", ["A Director"]),
        ("One, Two", ["One", "Two"]),
        ("One|Two", ["One", "Two"]),
        ("One;Two", ["One", "Two"]),
        # The reason the rule exists: a comma inside a name, in a list that uses pipes.
        ("Matthew, Jr.|Other", ["Matthew, Jr.", "Other"]),
        # And the cost of it: the same name in a comma-separated list is two people.
        ("Matthew, Jr.", ["Matthew", "Jr."]),
    ],
)
def test_which_separator_a_director_list_uses_depends_on_its_content(
    tmp_path: Path, written: str, expected: list[str]
) -> None:
    sidecar = tmp_path / "movie.nfo"
    sidecar.write_text(f"<movie><director>{written}</director></movie>", encoding="utf-8")
    people = read_nfo(sidecar, ItemType.MOVIE).values[Field.PEOPLE]
    assert isinstance(people, list)
    assert [person.name for person in people] == expected
    assert all(person.kind is PersonKind.DIRECTOR for person in people)


def test_an_actor_type_that_is_not_a_person_kind_falls_back_to_actor(tmp_path: Path) -> None:
    sidecar = tmp_path / "movie.nfo"
    sidecar.write_text(
        "<movie><actor><name>A</name><type>Composer</type></actor>"
        "<actor><name>B</name><type>Sparkle</type></actor></movie>",
        encoding="utf-8",
    )
    people = read_nfo(sidecar, ItemType.MOVIE).values[Field.PEOPLE]
    assert isinstance(people, list)
    assert [person.kind for person in people] == [PersonKind.COMPOSER, PersonKind.ACTOR]


def test_an_actor_with_no_name_is_not_a_person(tmp_path: Path) -> None:
    sidecar = tmp_path / "movie.nfo"
    sidecar.write_text("<movie><actor><role>The Lead</role></actor></movie>", encoding="utf-8")
    assert Field.PEOPLE not in read_nfo(sidecar, ItemType.MOVIE).values


def test_an_explicit_order_is_kept(tmp_path: Path) -> None:
    sidecar = tmp_path / "movie.nfo"
    sidecar.write_text(
        "<movie><actor><name>A</name><order>2</order></actor>"
        "<actor><name>B</name><sortorder>0</sortorder></actor></movie>",
        encoding="utf-8",
    )
    people = read_nfo(sidecar, ItemType.MOVIE).values[Field.PEOPLE]
    assert isinstance(people, list)
    assert [person.sort_order for person in people] == [2, 0]


# ----------------------------------------------------------------------------------------------
# Discovery
# ----------------------------------------------------------------------------------------------


def test_a_film_prefers_the_sidecar_named_after_it(tmp_path: Path) -> None:
    """A folder holding two films has a `movie.nfo` that can only describe one of them, so the
    per-file name has to win."""
    (tmp_path / "Film (1999).nfo").write_text("<movie/>", encoding="utf-8")
    (tmp_path / "movie.nfo").write_text("<movie/>", encoding="utf-8")
    found = find_sidecar(tmp_path, ItemType.MOVIE, stem="Film (1999)")
    assert found is not None
    assert found.name == "Film (1999).nfo"


def test_a_folder_per_film_layout_falls_back_to_movie_nfo(tmp_path: Path) -> None:
    (tmp_path / "movie.nfo").write_text("<movie/>", encoding="utf-8")
    found = find_sidecar(tmp_path, ItemType.MOVIE, stem="Film (1999)")
    assert found is not None
    assert found.name == "movie.nfo"


@pytest.mark.parametrize(
    ("kind", "name"),
    [
        (ItemType.SERIES, "tvshow.nfo"),
        (ItemType.SEASON, "season.nfo"),
        (ItemType.MUSIC_ALBUM, "album.nfo"),
        (ItemType.MUSIC_ARTIST, "artist.nfo"),
    ],
)
def test_each_container_has_its_own_sidecar_name(tmp_path: Path, kind: ItemType, name: str) -> None:
    (tmp_path / name).write_text("<x/>", encoding="utf-8")
    found = find_sidecar(tmp_path, kind)
    assert found is not None
    assert found.name == name


def test_an_episode_is_named_after_its_file(tmp_path: Path) -> None:
    (tmp_path / "The Series - S01E01 - The Pilot.nfo").write_text("<x/>", encoding="utf-8")
    found = find_sidecar(tmp_path, ItemType.EPISODE, stem="The Series - S01E01 - The Pilot")
    assert found is not None


def test_a_track_has_no_sidecar_of_its_own(tmp_path: Path) -> None:
    """Spec section 3.2's table has no row for one: music metadata comes from the file's own tags,
    and the sidecar in music's chain is beside its album or its artist."""
    (tmp_path / "01 - First.nfo").write_text("<x/>", encoding="utf-8")
    assert find_sidecar(tmp_path, ItemType.AUDIO, stem="01 - First") is None


def test_nothing_there_is_nothing(tmp_path: Path) -> None:
    assert find_sidecar(tmp_path, ItemType.MOVIE, stem="Absent") is None


# ----------------------------------------------------------------------------------------------
# The remaining fixtures parse
# ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("tvshow.nfo", ItemType.SERIES),
        ("season.nfo", ItemType.SEASON),
        ("episode.nfo", ItemType.EPISODE),
        ("album.nfo", ItemType.MUSIC_ALBUM),
        ("artist.nfo", ItemType.MUSIC_ARTIST),
    ],
)
def test_every_row_of_the_discovery_table_has_a_fixture_that_parses(
    name: str, kind: ItemType
) -> None:
    found = values_of(name, kind)
    assert found[Field.NAME], f"{name} produced no name"


def test_an_artists_biography_is_its_overview() -> None:
    """`<biography>` rather than `<plot>`, and both reach the same field: an artist item's
    description is served through the same property as a film's."""
    assert values_of("artist.nfo", ItemType.MUSIC_ARTIST)[Field.OVERVIEW] == (
        "An artist-level sidecar."
    )


def test_an_episodes_air_date_is_its_premiere_date() -> None:
    assert values_of("episode.nfo", ItemType.EPISODE)[Field.PREMIERE_DATE] == datetime(
        2010, 9, 1, tzinfo=UTC
    )


# ----------------------------------------------------------------------------------------------
# Nothing here writes
# ----------------------------------------------------------------------------------------------


def test_reading_every_fixture_leaves_the_tree_byte_identical() -> None:
    """AC-15's ancestor, at module level. The tree hash arrives at T10 over a whole scan; this is
    the cheap half, and it fails in the module that would have caused it."""
    import hashlib

    def digest() -> dict[str, str]:
        return {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(FIXTURES.iterdir())
            if path.is_file()
        }

    before = digest()
    for path in sorted(FIXTURES.iterdir()):
        if path.is_file():
            read_nfo(path, ItemType.MOVIE)
    assert digest() == before
