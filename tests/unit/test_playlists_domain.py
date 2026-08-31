# SPDX-License-Identifier: GPL-3.0-or-later
"""009 T1: the three permission functions, and the move arithmetic against a measured table.

**The first matrix is a transcription, not a model.** Every (source, target) pair below was
measured against a real reference server, all thirty of them, because until then the whole 25-row
matrix 009 spec section 6 asks for would have been a model derived from the single pair OQ-1
measured - `0 -> 3` - and a 25-row test of a model is a test of the model.
`[probe: tools/probe_playlist_move.py, Jellyfin 10.11.11, 2026-08-31]`

**The second matrix has no reference answer, and that is the finding rather than a gap.** It is the
caller who cannot see one entry, and the reference's arithmetic for that caller lands the entry one
position short of where it was asked to go, on any downward move
`[source: Emby.Server.Implementations/Playlists/PlaylistManager.cs:289-345 @ v10.11.11]`. It can
only fire for the entries the reference hides, which is a parental-rating check and never a library
one - so nothing Atrium hides (behaviours section 3.17) can ever produce it, and the rows here are
Atrium's rule: the entry lands where the caller asked, in the caller's own list.
"""

from __future__ import annotations

import pytest

from atrium.domain.playlists import (
    MoveIndexOutOfRangeError,
    Playlist,
    Share,
    may_delete,
    may_edit,
    may_read,
    moved,
)
from atrium.domain.user import User

FULL = ("A", "B", "C", "D", "E")

OWNER = User(id="owner", name="owner")
SHARED_EDITOR = User(id="editor", name="editor")
SHARED_READER = User(id="reader", name="reader")
STRANGER = User(id="stranger", name="stranger")
ADMIN = User(id="admin", name="admin", is_administrator=True)

PRIVATE = Playlist(
    id="playlist",
    name="a playlist",
    owner_user_id=OWNER.id,
    shares=(Share(SHARED_EDITOR.id, can_edit=True), Share(SHARED_READER.id, can_edit=False)),
)
PUBLIC = Playlist(id="public", name="public", owner_user_id=OWNER.id, is_public=True)


# ----------------------------------------------------------------------------------------------
# Section 3.7's table, one row per class of caller
# ----------------------------------------------------------------------------------------------

#: (label, playlist, user, may_read, may_edit, may_delete) - spec section 3.7, measured at the
#: spec-review gate. The administrator row is the one that document had wrong: an administrator
#: who neither owns the playlist nor is shared with it may delete it and may do nothing else.
PERMISSIONS = (
    ("the owner", PRIVATE, OWNER, True, True, True),
    ("a share with can_edit", PRIVATE, SHARED_EDITOR, True, True, False),
    ("a share without can_edit", PRIVATE, SHARED_READER, True, False, False),
    ("a stranger, private", PRIVATE, STRANGER, False, False, False),
    ("a stranger, public", PUBLIC, STRANGER, True, False, False),
    ("an administrator, private", PRIVATE, ADMIN, False, False, True),
    ("an administrator, public", PUBLIC, ADMIN, True, False, True),
)


@pytest.mark.parametrize(
    ("playlist", "user", "read", "edit", "delete"),
    [row[1:] for row in PERMISSIONS],
    ids=[row[0] for row in PERMISSIONS],
)
def test_the_three_permissions(
    playlist: Playlist, user: User, read: bool, edit: bool, delete: bool
) -> None:
    assert may_read(playlist, user) is read
    assert may_edit(playlist, user) is edit
    assert may_delete(playlist, user) is delete


def test_only_delete_reads_the_administrator_flag() -> None:
    """The asymmetry, asserted as itself: promoting a stranger changes exactly one answer."""
    promoted = User(id=STRANGER.id, name=STRANGER.name, is_administrator=True)
    assert may_read(PRIVATE, promoted) == may_read(PRIVATE, STRANGER)
    assert may_edit(PRIVATE, promoted) == may_edit(PRIVATE, STRANGER)
    assert may_delete(PRIVATE, promoted) is not may_delete(PRIVATE, STRANGER)


def test_a_share_never_grants_deletion() -> None:
    assert may_edit(PRIVATE, SHARED_EDITOR) is True
    assert may_delete(PRIVATE, SHARED_EDITOR) is False


# ----------------------------------------------------------------------------------------------
# The matrix, transcribed from the reference
# ----------------------------------------------------------------------------------------------

#: Rows are the source entry, columns are `newIndex` 0 to 5 inclusive, on [A B C D E]. Column 5 is
#: the clamp: an index equal to the entry count is the last position, on every source and not only
#: on the one the boundary battery asked about.
MEASURED = {
    "A": ("ABCDE", "BACDE", "BCADE", "BCDAE", "BCDEA", "BCDEA"),
    "B": ("BACDE", "ABCDE", "ACBDE", "ACDBE", "ACDEB", "ACDEB"),
    "C": ("CABDE", "ACBDE", "ABCDE", "ABDCE", "ABDEC", "ABDEC"),
    "D": ("DABCE", "ADBCE", "ABDCE", "ABCDE", "ABCED", "ABCED"),
    "E": ("EABCD", "AEBCD", "ABECD", "ABCED", "ABCDE", "ABCDE"),
}


@pytest.mark.parametrize("entry", sorted(MEASURED))
@pytest.mark.parametrize("new_index", range(6))
def test_every_source_and_target_matches_the_reference(entry: str, new_index: int) -> None:
    assert "".join(moved(FULL, entry, new_index, FULL)) == MEASURED[entry][new_index]


def test_the_pair_that_distinguishes_the_two_readings() -> None:
    """OQ-1's discriminator, spelled out: the entry ends up **at** `newIndex`, not before it.

    Named separately from the matrix because it is the one pair the whole feature was specified
    against, and a failure here should say which question it answers.
    """
    assert "".join(moved(FULL, "A", 3, FULL)) == "BCDAE"


def test_every_entry_survives_a_move() -> None:
    """Entry identifiers survive a move (spec section 3.5), which for a pure function is this."""
    for entry in FULL:
        for new_index in range(6):
            assert sorted(moved(FULL, entry, new_index, FULL)) == sorted(FULL)


# ----------------------------------------------------------------------------------------------
# The boundaries
# ----------------------------------------------------------------------------------------------

ABSENT = "Z"


def test_an_index_one_past_the_count_is_the_last_position() -> None:
    assert "".join(moved(FULL, "A", 5, FULL)) == "BCDEA"


@pytest.mark.parametrize("new_index", [-1, -5, 6, 7])
def test_an_index_outside_the_clamp_is_refused(new_index: int) -> None:
    with pytest.raises(MoveIndexOutOfRangeError):
        moved(FULL, "A", new_index, FULL)


def test_an_absent_entry_with_an_index_in_range_changes_nothing() -> None:
    assert moved(FULL, ABSENT, 2, FULL) == FULL


def test_the_index_is_judged_before_the_entry_is_looked_up() -> None:
    """Parity, and the row spec section 3.5 had wrong for the longest.

    An entry that is not in the playlist is a silent success when the index is in range and the
    refusal when it is not - the reference reaches the bounds first, and so does this.
    """
    assert moved(FULL, ABSENT, 5, FULL) == FULL
    with pytest.raises(MoveIndexOutOfRangeError):
        moved(FULL, ABSENT, 6, FULL)


def test_moving_to_its_current_index_changes_nothing() -> None:
    for index, entry in enumerate(FULL):
        assert moved(FULL, entry, index, FULL) == FULL


def test_a_one_entry_playlist_moves_to_both_of_its_indices() -> None:
    assert moved(("A",), "A", 0, ("A",)) == ("A",)
    assert moved(("A",), "A", 1, ("A",)) == ("A",)
    with pytest.raises(MoveIndexOutOfRangeError):
        moved(("A",), "A", 2, ("A",))


def test_an_empty_playlist_refuses_anything_past_zero() -> None:
    assert moved((), ABSENT, 0, ()) == ()
    with pytest.raises(MoveIndexOutOfRangeError):
        moved((), ABSENT, 1, ())


# ----------------------------------------------------------------------------------------------
# The second matrix: the same playlist, read by somebody who cannot see C
# ----------------------------------------------------------------------------------------------

VISIBLE = ("A", "B", "D", "E")

#: Rows are the source, columns are `newIndex` 0 to 4 - and 4 is the clamp, because the count the
#: bound is judged against is the count this caller can see. The values are the **full** order
#: afterwards, C included, which is what the store holds; the assertion below re-derives the
#: caller's own view from it and checks the entry landed where it asked.
HIDDEN = {
    "A": ("ABCDE", "BCADE", "BCDAE", "BCDEA", "BCDEA"),
    "B": ("BACDE", "ABCDE", "ACDBE", "ACDEB", "ACDEB"),
    "C": ("ABCDE", "ABCDE", "ABCDE", "ABCDE", "ABCDE"),
    "D": ("DABCE", "ADBCE", "ABCDE", "ABCED", "ABCED"),
    "E": ("EABCD", "AEBCD", "ABCED", "ABCDE", "ABCDE"),
}


@pytest.mark.parametrize("entry", sorted(HIDDEN))
@pytest.mark.parametrize("new_index", range(5))
def test_a_hidden_entry_does_not_move_the_visible_ones(entry: str, new_index: int) -> None:
    assert "".join(moved(FULL, entry, new_index, VISIBLE)) == HIDDEN[entry][new_index]


@pytest.mark.parametrize("entry", sorted(set(VISIBLE)))
@pytest.mark.parametrize("new_index", range(5))
def test_the_entry_lands_where_the_caller_asked_in_the_callers_own_list(
    entry: str, new_index: int
) -> None:
    """The property the second matrix exists for, asserted independently of its table.

    The caller sees four entries; asking for index 4 - one past their count - is the last
    position, exactly as index 5 is for the owner who sees five.
    """
    after = moved(FULL, entry, new_index, VISIBLE)
    seen = [item for item in after if item in VISIBLE]
    assert seen.index(entry) == min(new_index, len(seen) - 1)


def test_the_hidden_entry_is_not_addressable_by_a_caller_who_cannot_see_it() -> None:
    """Atrium's answer for C, and it is the absent-entry answer (behaviours section 3.17).

    The reference would move it: it looks the entry up in the stored list, which is not the list
    it bounded the index against. Under 009's omission divergence that entry is one this reader
    was never shown, so it is one they cannot reorder.
    """
    assert moved(FULL, "C", 0, VISIBLE) == FULL


def test_the_bound_follows_the_callers_own_count() -> None:
    with pytest.raises(MoveIndexOutOfRangeError):
        moved(FULL, "A", 5, VISIBLE)


def test_a_visible_list_that_is_not_a_view_of_the_order_is_a_programming_error() -> None:
    """Not a `400`: a route that hands these two lists in the wrong order has a bug, not a caller.

    `MoveIndexOutOfRangeError` is the class a route catches, and this is deliberately not one
    of them.
    """
    with pytest.raises(ValueError) as raised:
        moved(FULL, "A", 0, ("A", "Z"))
    assert not isinstance(raised.value, MoveIndexOutOfRangeError)

    with pytest.raises(ValueError) as reordered:
        moved(FULL, "A", 0, ("B", "A"))
    assert not isinstance(reordered.value, MoveIndexOutOfRangeError)
