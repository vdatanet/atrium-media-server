# SPDX-License-Identifier: GPL-3.0-or-later
"""009 T10: the order an artist expands in, which is the one ordering `sortBy` cannot express.

A folder is expanded in the folder's own order and an **artist** is not: the reference states
three keys for that query - album artist, then album, then sort name
`[source: MediaBrowser.Controller/Playlists/Playlist.cs:205-215 @ v10.11.11]` - and measured, its
answer is that ordering and **not** the album-by-album order a walk down the item tree produces:
forty-two rows against forty, differing from the first position
`[probe: tools/probe_playlist_expansion.py, Jellyfin 10.11.11, 2026-09-01]`.

The middle key is why this test is here rather than at the HTTP boundary. `Album` is not one of
the eight tokens `sortBy` accepts and `SortBy`'s own docstring forbids a ninth, so the ordering is
applied to the hydrated rows instead - and the seeded world cannot tell it from a plain sort by
name, because its one guest album's artist sorts before its compilation's under both rules.
Asserting it where it lives is the honest alternative to asserting it where it happens to agree.
"""

from __future__ import annotations

from atrium.api.playlists import _by_album_artist_album_and_name
from atrium.db.item_queries import Ancestor, HydratedItem
from atrium.domain.items import Item, ItemType


def track(name: str, album: str, album_artist: str, ident: str) -> HydratedItem:
    """One track with the two ancestors the ordering reads: its album and that album's artist."""
    return HydratedItem(
        item=Item(
            id=ident,
            type=ItemType.AUDIO,
            name=name,
            library_id="library",
            sort_name=name.lower(),
        ),
        parent=Ancestor(id=f"album-{album}", type=ItemType.MUSIC_ALBUM, name=album),
        grandparent=Ancestor(
            id=f"artist-{album_artist}", type=ItemType.MUSIC_ARTIST, name=album_artist
        ),
    )


def test_the_albums_are_grouped_where_a_sort_by_name_would_interleave_them() -> None:
    """The discriminating case: two albums whose track names alternate.

    Under the reference's three keys the two albums arrive whole, one after the other. Under a
    plain `SortName` - which is what a query without the middle key gives - they interleave, and
    a client sees a shuffled artist.
    """
    rows = [
        track("Beta", "Second", "One Artist", "b"),
        track("Alpha", "First", "One Artist", "a"),
        track("Delta", "Second", "One Artist", "d"),
        track("Charlie", "First", "One Artist", "c"),
    ]
    assert [one.id for one in sorted(rows, key=_by_album_artist_album_and_name)] == [
        "a",
        "c",
        "b",
        "d",
    ]
    assert [one.id for one in sorted(rows, key=lambda one: one.item.sort_name)] == [
        "a",
        "b",
        "c",
        "d",
    ]


def test_the_album_artist_outranks_the_album_and_the_id_closes_the_order() -> None:
    """The first key and the last. A guest appearance sorts under the album's artist, not the
    performer's, and two rows that tie on all three keys still order the same way twice
    (Principle VII)."""
    guest = track("Alpha", "Zed Record", "Another Artist", "guest")
    own = track("Beta", "Album", "One Artist", "own")
    assert [one.id for one in sorted([own, guest], key=_by_album_artist_album_and_name)] == [
        "guest",
        "own",
    ]

    tied = [track("Same", "Album", "One Artist", ident) for ident in ("b", "a")]
    assert [one.id for one in sorted(tied, key=_by_album_artist_album_and_name)] == ["a", "b"]
