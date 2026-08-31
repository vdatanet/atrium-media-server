# SPDX-License-Identifier: GPL-3.0-or-later
"""Who may touch a playlist, and where a moved entry lands.

Feature 009's two pieces of decision-making, as functions of their arguments: no session, no ORM,
no request. Both are here for the same reason and it is not tidiness.

**The permissions are three functions rather than one flag** because the spec gate measured an
asymmetry nobody predicted: an administrator who neither owns a playlist nor is shared with it may
**delete** it and may not read or edit it - every editing route tests owner-or-share and has no
administrator branch, and deletion is the only route that has one
(009 spec section 3.7). One `can_manage(user)` would have to carry that asymmetry as an argument,
which is the shape that gets it wrong twice.

**The move is here because it is the one thing this feature can get wrong invisibly.** Its two
readings agree on every upward move and differ by one position on every downward one, which looks
like a client rendering glitch, so the whole matrix of source and target positions is asserted
against a reference measurement rather than against a plausible model
`[probe: tools/probe_playlist_move.py, Jellyfin 10.11.11, 2026-08-31]`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .user import User


class MoveIndexOutOfRangeError(ValueError):
    """A `newIndex` this server refuses: below zero, or past the caller's own entry count.

    009's third divergence (behaviours section 3.15). The reference crashes with `500` on the
    first and silently performs a move nobody asked for on the second; Atrium refuses both, and
    the route turns this into the `400` that says so.

    **A route catches this class and not `ValueError`.** `moved` raises a plain `ValueError` for a
    caller that contradicts itself - a visible list that is not a sub-sequence of the order it
    claims to be a view of - and that is a programming error, not a client's `400`.
    """


@dataclass(frozen=True, slots=True)
class Share:
    """One entry of the create body's `Users` (009 spec section 3.2).

    `can_edit` splits section 3.7's second and third classes of caller, and it is the only thing
    that distinguishes them: neither may delete.
    """

    user_id: str
    can_edit: bool = False


@dataclass(frozen=True, slots=True)
class Playlist:
    """A playlist, without its entries.

    The entries are not a field: they are read per caller and filtered per caller (009 plan
    section 6.5), so an object that carried them would carry one reader's view into every other
    reader's code path.

    No `Path` and no dates. The reference builds a playlist as a directory and reports all three;
    Atrium has no directory, and inventing a path no file backs would be the worse answer
    (009 spec section 4).
    """

    id: str
    name: str
    owner_user_id: str
    is_public: bool = False
    media_type: str = "Audio"
    shares: tuple[Share, ...] = ()


def _share_for(playlist: Playlist, user: User) -> Share | None:
    return next((share for share in playlist.shares if share.user_id == user.id), None)


def may_read(playlist: Playlist, user: User) -> bool:
    """The owner, anybody it is shared with, and everybody when it is public.

    **An administrator gets nothing here**, which is the row 009 spec section 3.7 had wrong until
    the gate measured it: a private playlist answers `404` to an administrator who does not own it,
    exactly as it does to anybody else. What an administrator may do is name another user on the
    read route - which is a question about the *caller*, answered before this function is reached.
    """
    return (
        playlist.is_public
        or user.id == playlist.owner_user_id
        or _share_for(playlist, user) is not None
    )


def may_edit(playlist: Playlist, user: User) -> bool:
    """The owner, and a share that carries `can_edit`.

    Public does not imply editable, and neither does administrator.
    """
    share = _share_for(playlist, user)
    return user.id == playlist.owner_user_id or (share is not None and share.can_edit)


def may_delete(playlist: Playlist, user: User) -> bool:
    """The owner, and an administrator.

    The only one of the three that reads `is_administrator`, and deletion is the one operation an
    administrator may perform on a playlist they do not own
    `[source: MediaBrowser.Controller/Playlists/Playlist.cs:261-264 @ v10.11.11]`. A share never
    grants it, whatever `can_edit` says.
    """
    return user.id == playlist.owner_user_id or user.is_administrator


def _is_sub_sequence(part: Sequence[str], whole: Sequence[str]) -> bool:
    iterator = iter(whole)
    return all(any(candidate == entry for candidate in iterator) for entry in part)


def moved(
    order: Sequence[str],
    entry: str,
    new_index: int,
    visible: Sequence[str],
) -> tuple[str, ...]:
    """The playlist's full order after moving `entry` to `new_index` of the caller's view.

    `order` is every entry; `visible` is the sub-sequence this caller may see (009 plan section
    6.5's filter). A caller who sees everything passes the same sequence twice, and that is the
    owner's case and almost every test's.

    **Both indices are the caller's.** The bound is `len(visible)`, and the entry ends up at
    `new_index` of the caller's list rather than of the stored one. The bound is parity - the
    reference indexes the accessible children too, which is why an index one past that count is
    the last position and two past it is its `500`. The landing position is **not**: the reference
    computes the neighbour's position in the order *before* the entry is removed and inserts after
    it, so on a list with anything hidden a downward move lands one short of where the caller asked
    `[source: Emby.Server.Implementations/Playlists/PlaylistManager.cs:289-345 @ v10.11.11]`. That
    only fires for entries the reference hides, which is a parental-rating check and never a
    library one - so it cannot fire on the set Atrium hides (behaviours section 3.17), and there is
    no reference answer here to reproduce. Atrium puts the entry where the caller asked.

    An entry the caller cannot see is not addressable: it is answered exactly as an entry that is
    not in the playlist at all, with the order unchanged.

    Raises `MoveIndexOutOfRangeError` for an index below zero or past `len(visible)` -
    **before** asking whether the entry exists, which is the order the reference judges in and is
    parity
    (009 plan section 6.4.1).
    """
    full = list(order)
    seen = list(visible)
    if not _is_sub_sequence(seen, full):
        raise ValueError("`visible` is not a sub-sequence of `order`: they describe two playlists")

    if new_index < 0 or new_index > len(seen):
        raise MoveIndexOutOfRangeError(
            f"newIndex {new_index} is outside 0..{len(seen)} for a caller who sees "
            f"{len(seen)} entr{'y' if len(seen) == 1 else 'ies'}"
        )
    if entry not in seen:
        return tuple(full)
    if seen.index(entry) == new_index:
        return tuple(full)

    full.remove(entry)
    seen.remove(entry)
    if new_index >= len(seen):
        full.append(entry)
    else:
        full.insert(full.index(seen[new_index]), entry)
    return tuple(full)


__all__ = [
    "MoveIndexOutOfRangeError",
    "Playlist",
    "Share",
    "may_delete",
    "may_edit",
    "may_read",
    "moved",
]
