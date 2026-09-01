# SPDX-License-Identifier: GPL-3.0-or-later
"""One read door, six writes, and the three properties a route cannot check for itself.

009 T7. What is asserted here is what a conformance test at the HTTP boundary would see only by
accident:

* **`ordinal` is contiguous after every mutation.** Nothing on the wire reads the column, and
  every operation on a playlist assumes it: a gap is invisible until a `Move` computes a landing
  position from it.
* **An entry is filtered by the reader, in one place.** The repository asks
  `ItemQueryRepository` the same question `/Items` asks rather than carrying a second predicate,
  so a change to library access cannot move one and leave the other.
* **Every read takes a `User`** - plan section 9's second risk, asserted by reflection so that a
  method added later has to be classified before the suite is green.
"""

from __future__ import annotations

import inspect
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session as OrmSession

from atrium.config.paths import DataPaths
from atrium.db import models, schema
from atrium.db.engine import create_database_engine, session_factory
from atrium.db.item_queries import ItemQueryRepository
from atrium.db.repositories import ItemRepository, PlaylistRepository
from atrium.domain.items import ItemType
from atrium.domain.playlists import (
    MoveIndexOutOfRangeError,
    Playlist,
    Share,
    may_delete,
)
from atrium.domain.user import User
from tests.conftest import data_dir
from tests.fixtures.query import QueryWorld, build_query_world

#: Minted, and a constant rather than `new_id()`: a deterministic world (Principle VII) cannot
#: have an identifier that changes per run, and these must not collide with the fixture's five.
MADE = "7a" * 16
SECOND = "7b" * 16

REMOVED_AT = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    prepared: DataPaths = data_dir(tmp_path / "atrium")
    built = create_database_engine(prepared)
    schema.ensure_current(built, prepared)
    yield built
    built.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[OrmSession]:
    opened = session_factory(engine)()
    yield opened
    opened.rollback()
    opened.close()


@pytest.fixture
def world(session: OrmSession) -> QueryWorld:
    built = build_query_world(session)
    session.commit()
    return built


@pytest.fixture
def playlists(session: OrmSession) -> PlaylistRepository:
    return PlaylistRepository(session, ItemQueryRepository(session))


def ordinals(session: OrmSession, playlist_id: str) -> list[int]:
    """Every stored ordinal, in the order the rows are read back."""
    return list(
        session.execute(
            select(models.PlaylistEntry.ordinal)
            .where(models.PlaylistEntry.playlist_id == playlist_id)
            .order_by(models.PlaylistEntry.ordinal)
        ).scalars()
    )


def is_contiguous(session: OrmSession, playlist_id: str) -> bool:
    stored = ordinals(session, playlist_id)
    return stored == list(range(len(stored)))


def administrator() -> User:
    """Built here because the fixture world has none, the way `test_items_route.py` does it.

    It must not claim `"d" * 32`, which that file's own administrator already holds (T5).
    """
    return User(id="e" * 32, name="admin", name_normalised="admin", is_administrator=True)


# ------------------------------------------------------------------------------------------
# The one read door
# ------------------------------------------------------------------------------------------


def test_by_id_carries_the_stored_media_type_rather_than_deriving_one(
    playlists: PlaylistRepository, world: QueryWorld
) -> None:
    """T6 filled the same column on the `/Items` path, and two derivations would disagree."""
    audio = playlists.by_id(world.public_playlist.id, world.everyone)
    video = playlists.by_id(world.private_playlist.id, world.everyone)
    assert audio is not None and video is not None
    assert (audio.media_type, video.media_type) == ("Audio", "Video")


def test_by_id_refuses_a_playlist_this_caller_may_not_read(
    playlists: PlaylistRepository, world: QueryWorld
) -> None:
    """Spec section 3.3: `404` and not `403`, so the identifier discloses nothing."""
    assert playlists.by_id(world.private_playlist.id, world.restricted) is None
    assert playlists.by_id(world.public_playlist.id, world.restricted) is not None
    assert playlists.by_id(world.shared_playlist.id, world.restricted) is not None


def test_by_id_hands_an_administrator_the_playlist_they_may_not_read(
    playlists: PlaylistRepository, world: QueryWorld
) -> None:
    """The one caller a `may_read` filter would break: deletion is theirs (spec section 3.6).

    The row comes back and `may_read` still says no - that call is the read route's, and this
    test exists so that tightening the door here fails loudly rather than making T12 unwritable.
    """
    from atrium.domain.playlists import may_delete, may_read

    found = playlists.by_id(world.private_playlist.id, administrator())
    assert found is not None
    assert not may_read(found, administrator())
    assert may_delete(found, administrator())


def test_by_id_for_deletion_hands_over_a_playlist_no_reader_could_see(
    playlists: PlaylistRepository, world: QueryWorld
) -> None:
    """The third read, and the whole of why it exists (T12).

    `restricted` is refused this playlist by `by_id` and by every route in the feature; the
    deletion route still has to reach it, because the reference answers that caller `401` and not
    `404` `[probe: tools/probe_item_deletion.py, Jellyfin 10.11.11, 2026-09-01]`. What the row is
    *for* is `may_delete`, which still says no - the door is not the decision.
    """
    found = playlists.by_id_for_deletion(world.private_playlist.id)
    assert found is not None
    assert not may_delete(found, world.restricted)
    assert may_delete(found, world.everyone)
    assert playlists.by_id(world.private_playlist.id, world.restricted) is None


def test_by_id_for_deletion_answers_nothing_for_an_item_that_is_not_a_playlist(
    playlists: PlaylistRepository, world: QueryWorld
) -> None:
    """A film and an unknown identifier are one answer, which is what lets the route tell "not a
    playlist" from "not permitted" without a second query."""
    assert playlists.by_id_for_deletion(world.corpus[0]) is None
    assert playlists.by_id_for_deletion("f" * 32) is None


def test_by_id_reads_the_shares_that_decide_the_three_permissions(
    playlists: PlaylistRepository, world: QueryWorld
) -> None:
    found = playlists.by_id(world.read_only_playlist.id, world.everyone)
    assert found is not None
    assert found.shares == (Share(user_id=world.restricted.id, can_edit=False),)


def test_entries_are_the_stored_order_for_a_reader_who_sees_everything(
    playlists: PlaylistRepository, world: QueryWorld
) -> None:
    assert playlists.entries(world.private_playlist.id, world.everyone) == list(
        world.private_playlist.entries
    )


def test_entries_omit_what_the_reader_cannot_reach_and_keep_the_rest_in_order(
    playlists: PlaylistRepository, world: QueryWorld
) -> None:
    """Behaviours section 3.17, at the level that decides it. The fixture interleaves the hidden
    entries, so an implementation that appended the survivors would fail here.
    """
    handle = world.cross_library_playlist
    assert handle.beyond_restricted, "the fixture must hold entries this reader cannot reach"
    assert playlists.entries(handle.id, world.restricted) == list(handle.restricted_sees)


def test_an_entry_whose_item_is_soft_deleted_disappears_and_comes_back(
    playlists: PlaylistRepository, session: OrmSession, world: QueryWorld
) -> None:
    """The reference drops entries whose item does not resolve, and a returning file is 003's
    whole argument for soft deletion: the row stays, so the playlist survives a remount.
    """
    handle = world.private_playlist
    gone = handle.entries[2]
    items = ItemRepository(session)

    items.mark_removed([gone], REMOVED_AT)
    assert playlists.entries(handle.id, world.everyone) == [
        one for one in handle.entries if one != gone
    ]

    items.revive([gone])
    assert playlists.entries(handle.id, world.everyone) == list(handle.entries)


# ------------------------------------------------------------------------------------------
# Creating and appending
# ------------------------------------------------------------------------------------------


def made(world: QueryWorld, playlist_id: str = MADE, **changed: object) -> Playlist:
    fields: dict[str, object] = {
        "id": playlist_id,
        "name": "Made by the repository",
        "owner_user_id": world.everyone.id,
        "media_type": "Video",
    }
    fields.update(changed)
    return Playlist(**fields)  # type: ignore[arg-type]


def test_create_writes_an_item_row_with_no_library(
    playlists: PlaylistRepository, session: OrmSession, world: QueryWorld
) -> None:
    """Half of `ck_items_by_name_has_no_library`, widened by 0008 for this row (plan 4.1)."""
    playlists.create(made(world), world.corpus[:3])
    row = session.get(models.Item, MADE)
    assert row is not None
    assert (row.type, row.library_id) == (ItemType.PLAYLIST.value, None)
    assert row.date_created is not None, "a playlist with no creation date sorts nowhere"


def test_create_is_visible_through_the_read_door_it_did_not_go_through(
    playlists: PlaylistRepository, world: QueryWorld
) -> None:
    playlists.create(made(world, shares=(Share(user_id=world.restricted.id, can_edit=True),)), ())
    found = playlists.by_id(MADE, world.restricted)
    assert found is not None
    assert found.name == "Made by the repository"
    assert found.shares == (Share(user_id=world.restricted.id, can_edit=True),)


def test_create_de_duplicates_the_id_list_and_keeps_the_first_occurrence(
    playlists: PlaylistRepository, session: OrmSession, world: QueryWorld
) -> None:
    """Measured on the reference, where `Ids` naming A B A creates a playlist holding A B
    `[probe: tools/probe_playlist_writes.py, Jellyfin 10.11.11, 2026-08-31]`.
    """
    first, second = world.corpus[0], world.corpus[1]
    playlists.create(made(world), (first, second, first))
    assert playlists.entries(MADE, world.everyone) == [first, second]
    assert is_contiguous(session, MADE)


def test_appending_something_already_there_adds_nothing_and_moves_nothing(
    playlists: PlaylistRepository, session: OrmSession, world: QueryWorld
) -> None:
    """ "Kept in place", not "re-seated at the end" - the half a one-entry playlist cannot show
    `[probe: tools/probe_playlist_writes.py, Jellyfin 10.11.11, 2026-08-31]`.
    """
    kept = world.corpus[:3]
    playlists.create(made(world), kept)
    assert playlists.append(MADE, [kept[0]]) == 0
    assert playlists.entries(MADE, world.everyone) == list(kept)
    assert is_contiguous(session, MADE)


def test_a_batch_of_duplicates_and_new_ids_leaves_no_hole_in_the_ordinals(
    playlists: PlaylistRepository, session: OrmSession, world: QueryWorld
) -> None:
    """The finding this task paid for: the primary key alone would drop the row **and** the
    ordinal it was going to occupy, so the column three other operations assume is contiguous
    would develop a hole on the first repeated add.
    """
    kept = world.corpus[:2]
    playlists.create(made(world), kept)
    added = playlists.append(MADE, [kept[0], world.corpus[2], world.corpus[3], world.corpus[2]])
    assert added == 2
    assert playlists.entries(MADE, world.everyone) == [*kept, world.corpus[2], world.corpus[3]]
    assert ordinals(session, MADE) == [0, 1, 2, 3]


def test_appending_to_a_playlist_that_holds_nothing_starts_at_zero(
    playlists: PlaylistRepository, session: OrmSession, world: QueryWorld
) -> None:
    playlists.create(made(world), ())
    assert playlists.append(MADE, world.corpus[:2]) == 2
    assert ordinals(session, MADE) == [0, 1]


# ------------------------------------------------------------------------------------------
# Removing, reordering, renaming, deleting
# ------------------------------------------------------------------------------------------


def test_removing_from_the_middle_closes_the_gap(
    playlists: PlaylistRepository, session: OrmSession, world: QueryWorld
) -> None:
    five = world.corpus[:5]
    playlists.create(made(world), five)
    playlists.remove(MADE, [five[1], five[3]])
    assert playlists.entries(MADE, world.everyone) == [five[0], five[2], five[4]]
    assert ordinals(session, MADE) == [0, 1, 2]


def test_removing_something_that_is_not_there_is_not_an_error(
    playlists: PlaylistRepository, session: OrmSession, world: QueryWorld
) -> None:
    """Spec section 3.5: a client retrying a successful removal must not be refused."""
    three = world.corpus[:3]
    playlists.create(made(world), three)
    playlists.remove(MADE, [world.corpus[9], three[0]])
    assert playlists.entries(MADE, world.everyone) == list(three[1:])
    assert is_contiguous(session, MADE)


def test_reorder_moves_the_entry_and_renumbers(
    playlists: PlaylistRepository, session: OrmSession, world: QueryWorld
) -> None:
    """AC-9's measured pair, at the level below the route: `0 -> 3` on five entries."""
    five = list(world.corpus[:5])
    playlists.create(made(world), five)
    playlists.reorder(MADE, five[0], 3, five)
    assert playlists.entries(MADE, world.everyone) == [five[1], five[2], five[3], five[0], five[4]]
    assert ordinals(session, MADE) == [0, 1, 2, 3, 4]


def test_reorder_indexes_the_list_the_caller_was_given(
    playlists: PlaylistRepository, session: OrmSession, world: QueryWorld
) -> None:
    """AC-17's second half, and the only thing that exercises `moved`'s two lists through the
    store: the entry lands at the last index of the reader's own view, not of the stored five.

    Downward on purpose: the two readings of section 3.5 agree on every upward move.
    """
    handle = world.cross_library_playlist
    seen = playlists.entries(handle.id, world.restricted)
    playlists.reorder(handle.id, seen[0], len(seen) - 1, seen)
    assert playlists.entries(handle.id, world.restricted) == [*seen[1:], seen[0]]
    hidden = set(handle.beyond_restricted)
    assert {one for one in playlists.entries(handle.id, world.everyone) if one in hidden} == hidden
    assert is_contiguous(session, handle.id)


def test_reorder_refuses_an_index_past_the_callers_own_count(
    playlists: PlaylistRepository, world: QueryWorld
) -> None:
    """Raised by name: a plain `ValueError` beside it means the two lists were passed the wrong
    way round, which is a bug and not a client's `400` (T1).
    """
    handle = world.cross_library_playlist
    seen = playlists.entries(handle.id, world.restricted)
    with pytest.raises(MoveIndexOutOfRangeError):
        playlists.reorder(handle.id, seen[0], len(seen) + 1, seen)
    assert playlists.entries(handle.id, world.restricted) == seen


def test_rename_writes_all_three_derivations_of_the_name(
    playlists: PlaylistRepository, session: OrmSession, world: QueryWorld
) -> None:
    """`name`, `sort_name` and `name_folded`. Writing only the first leaves a playlist that sorts
    under its old name and that `searchTerm` cannot find at all - 005 T6's finding, one row of the
    same table.
    """
    playlists.create(made(world, name="The first name"), ())
    playlists.rename(MADE, "The Second Name")
    row = session.get(models.Item, MADE)
    assert row is not None
    assert row.name == "The Second Name"
    assert row.sort_name == "second name"
    assert row.name_folded == "the second name"


def test_delete_takes_the_entries_and_the_shares_with_it(
    playlists: PlaylistRepository, session: OrmSession, world: QueryWorld
) -> None:
    """A playlist is the one item that is not soft-deleted (plan section 4.5), and the cascade is
    the database's - which only holds because `db/engine.py` enforces foreign keys per connection.
    """
    playlists.create(
        made(world, shares=(Share(user_id=world.restricted.id, can_edit=True),)), world.corpus[:3]
    )
    session.flush()
    playlists.delete(MADE)
    session.expire_all()
    assert session.get(models.Item, MADE) is None
    assert session.get(models.Playlist, MADE) is None
    assert ordinals(session, MADE) == []
    assert (
        session.execute(
            select(models.PlaylistShare).where(models.PlaylistShare.playlist_id == MADE)
        ).first()
        is None
    )


def test_two_playlists_do_not_share_an_ordering(
    playlists: PlaylistRepository, world: QueryWorld
) -> None:
    """Every statement here is keyed by playlist, and a missing `WHERE` would be invisible in a
    world holding one.
    """
    playlists.create(made(world), world.corpus[:3])
    playlists.create(made(world, playlist_id=SECOND), world.corpus[3:5])
    playlists.remove(MADE, [world.corpus[0]])
    assert playlists.entries(SECOND, world.everyone) == list(world.corpus[3:5])


# ------------------------------------------------------------------------------------------
# The invariant, by reflection (plan section 9's second risk)
# ------------------------------------------------------------------------------------------

#: The classification, and the test below fails until a new method joins one of the three.
READS = {"by_id", "entries"}
WRITES = {"create", "append", "remove", "reorder", "rename", "delete"}

#: The reads that take no reader, and there is exactly one. `DELETE /Items/{itemId}` applies no
#: visibility test to a playlist - measured, a caller answered `404` by every other route is
#: answered `401` by that one `[probe: tools/probe_item_deletion.py, Jellyfin 10.11.11,
#: 2026-09-01]` - so the door it goes through cannot take a `User` and be honest about it. A set
#: rather than an exemption, so that a second unfiltered read has to be added here on purpose.
UNFILTERED_READS = {"by_id_for_deletion"}


def public_methods() -> set[str]:
    return {
        name
        for name, _ in inspect.getmembers(PlaylistRepository, inspect.isfunction)
        if not name.startswith("_")
    }


def test_every_public_method_is_classified_as_a_read_or_a_write() -> None:
    assert public_methods() == READS | WRITES | UNFILTERED_READS, (
        "a method was added to PlaylistRepository without being classified. A read must take a "
        "`User`; say which this is, in READS, in WRITES or in UNFILTERED_READS, and the two "
        "assertions below will hold you to it."
    )


@pytest.mark.parametrize("name", sorted(READS))
def test_a_read_takes_a_user(name: str) -> None:
    """Plan section 9: a read added without a `User` is how behaviours section 3.17's divergence
    stops applying on one route, silently, in a change that looks like a refactor.
    """
    parameters = inspect.signature(getattr(PlaylistRepository, name)).parameters
    assert "user" in parameters, f"PlaylistRepository.{name} reads without a reader"
    assert parameters["user"].annotation == "User"


@pytest.mark.parametrize("name", sorted(UNFILTERED_READS))
def test_an_unfiltered_read_takes_no_user(name: str) -> None:
    """The other half of the invariant: a read listed here must not quietly grow a reader.

    A `User` on this signature would read as a filter, and the whole point of the method is that
    the route it serves applies none - so the parameter would be either unused or a divergence.
    """
    parameters = inspect.signature(getattr(PlaylistRepository, name)).parameters
    assert "user" not in parameters, f"PlaylistRepository.{name} is classified as unfiltered"
