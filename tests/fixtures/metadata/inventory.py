# SPDX-License-Identifier: GPL-3.0-or-later
"""Every committed byte in this directory, by size and hash.

003 kept "no fixture file is a copyrighted work" true by asserting that `tests/fixtures` holds
nothing but `.py` files: a property rather than a list, because a list of forbidden extensions
passes for whichever extension nobody thought of. 004 cannot use that property - its whole
premise is committed bytes - so it uses the inverse one. **Nothing is here unless it is below**,
with the digest of the bytes it was committed with, and `tests/metadata/test_fixture_tree.py`
holds the two directions apart:

* a file in the tree and not in this table fails - that is the `.mkv` somebody helpfully added;
* a file in this table whose bytes moved fails - that is the poster somebody swapped in behind an
  unchanged name.

Adding to this table is therefore a deliberate act that shows up in a diff as a hash, which is the
review surface. The size caps in that test are the second half: a file small enough to pass them
is too small to be a recognisable piece of anybody's work, whatever the hash says.

Regenerate after a deliberate change with the command in README.md. The caps below are read from
disk rather than from this table, so raising one means editing this file rather than a fixture.
"""

from __future__ import annotations

#: Path relative to this directory -> the first 16 bytes of the SHA-256 of its bytes, as
#: 32 lowercase hex characters. Truncated because 128 bits is far past what "did these
#: bytes move?" needs, and because a full digest does not fit on a line with its path.
FILES: dict[str, str] = {
    "artwork/extensions/banner.webp": "4b36efd063dbeed780c197999be9ccfd",
    "artwork/extensions/disc.Jpeg": "fad584198e5a2483f966b5ef332749b1",
    "artwork/extensions/fanart.jpeg": "c483b2c786fd0cafa5e6d47a05bffb85",
    "artwork/extensions/logo.PNG": "8ff05cd475a542f4e56ab53c71ec6415",
    "artwork/extensions/poster.JPG": "a81eb3ed36b294d43b02cd98e7b89bb1",
    "artwork/names-first/backdrop.jpg": "3964c343f2d600dcbdaf993083f8f483",
    "artwork/names-first/background.jpg": "773651480a9020a0019d7ced317bd1fd",
    "artwork/names-first/banner.jpg": "3d5660a5f49e0463610a6fd077a7f96f",
    "artwork/names-first/cdart.jpg": "4654e1043880bd543d62f56c6d695675",
    "artwork/names-first/clearlogo.jpg": "861eec68e7e632ebaa296029950c626a",
    "artwork/names-first/cover.jpg": "79c6c4164f155d37f6e00b0d4dec5889",
    "artwork/names-first/default.jpg": "c30385559758e579bfc8e08d957665fc",
    "artwork/names-first/disc.jpg": "22971304fe10842463a34942ab9848ff",
    "artwork/names-first/fanart.jpg": "441597bcef896be292a6189da6b92161",
    "artwork/names-first/folder.jpg": "55fa8911016ac21794286f21879bb09c",
    "artwork/names-first/landscape.jpg": "d7327a24f28e9411b48c824204ef6c88",
    "artwork/names-first/logo.jpg": "02c6fa712fb8e1d3488ba64e794bb422",
    "artwork/names-first/poster.jpg": "60675e1ad68137e09fd71abe69350c9c",
    "artwork/names-first/thumb.jpg": "7d8c8278ee1817f8ec44ecd0f7a72297",
    "artwork/names-fourth/default.jpg": "c30385559758e579bfc8e08d957665fc",
    "artwork/names-second/backdrop.jpg": "3964c343f2d600dcbdaf993083f8f483",
    "artwork/names-second/background.jpg": "773651480a9020a0019d7ced317bd1fd",
    "artwork/names-second/cdart.jpg": "4654e1043880bd543d62f56c6d695675",
    "artwork/names-second/clearlogo.jpg": "861eec68e7e632ebaa296029950c626a",
    "artwork/names-second/cover.jpg": "79c6c4164f155d37f6e00b0d4dec5889",
    "artwork/names-second/default.jpg": "c30385559758e579bfc8e08d957665fc",
    "artwork/names-second/folder.jpg": "55fa8911016ac21794286f21879bb09c",
    "artwork/names-second/landscape.jpg": "d7327a24f28e9411b48c824204ef6c88",
    "artwork/names-third/background.jpg": "773651480a9020a0019d7ced317bd1fd",
    "artwork/names-third/cover.jpg": "79c6c4164f155d37f6e00b0d4dec5889",
    "artwork/names-third/default.jpg": "c30385559758e579bfc8e08d957665fc",
    "artwork/numbered-backdrops/fanart-1.jpg": "e67ad71ef5c03d46e58fb9553bec2949",
    "artwork/numbered-backdrops/fanart-10.jpg": "7f877de78f16f52c3f51ea3924fbb33d",
    "artwork/numbered-backdrops/fanart-2.jpg": "4b5dfa3efa9b6aafba1e965e5ab8acd6",
    "artwork/numbered-backdrops/fanart.jpg": "312c998447384bae83763bc1f74aa235",
    "artwork/numbered-backdrops/fanart3.jpg": "42f7f54d3b8ecae783b50df04dc1e2db",
    "artwork/per-item/Film (1999)-poster.jpg": "17e8a90e4075945059e037a002fc06f7",
    "artwork/per-item/poster.jpg": "cd0901eb8b12a9969c071cb1be2e232f",
    "artwork/unreadable/folder.png": "b9ba70775fa31930de0bb16d4cabca4d",
    "artwork/unreadable/poster.jpg": "9dc31697724d506017f5bc6f306fb394",
    "audio/template.flac": "de2132c1363254fc34f91ef37415e777",
    "audio/template.m4a": "92aaf91cd386b3beb350cd31e5ceebb2",
    "audio/template.mp3": "9de602a3261410be3d4792c43b9054da",
    "audio/template.ogg": "1484593bae7d9869231850ca05b7859b",
    "nfo/album.nfo": "8ec8bc503c859314a84e5e37f216fe4e",
    "nfo/artist.nfo": "fb8e715f5d4d15d93ab0caca4e05caae",
    "nfo/episode.nfo": "901f2d38a6e4467fdbb9f2e8dea140b4",
    "nfo/movie-entity-bomb.nfo": "f086be6c7250ea3d919e257b74d159e3",
    "nfo/movie-entity-external.nfo": "b494719cb6546041c93913f595f74e69",
    "nfo/movie-entity-internal.nfo": "625b73f51cd3990a0d97a7b4b1b9f514",
    "nfo/movie-full.nfo": "33460bbc45c0c0c78015cb69429a03d0",
    "nfo/movie-ids.nfo": "6533eacb7ceadd44b34efc852d86c11b",
    "nfo/movie-malformed.nfo": "d34c4596c6697eacd69038245fac346b",
    "nfo/movie-sparse.nfo": "a75362a39f0c68b3bd51f7a29666c4e6",
    "nfo/season.nfo": "45ab0b845123c4a7bb47e61c8016a56f",
    "nfo/tvshow.nfo": "73c5c4e67f22e970bb61f8a45e69e9f0",
}

#: No single fixture may exceed this. The largest today is the Ogg template at 3,773 bytes; the
#: cap is set at roughly twice that so a new container has room and a real song has none.
MAX_FILE_BYTES = 8 * 1024

#: Nor may the tree as a whole. 20,718 bytes today.
MAX_TREE_BYTES = 64 * 1024

#: Text fixtures say what they are in their own bytes, the way 003's generated files do, so a
#: human who opens one does not have to read this module. These two are documentation and code.
NOT_SELF_DESCRIBING = frozenset({"README.md", "inventory.py", "__init__.py"})

#: The phrase every other text fixture carries.
BANNER = "atrium synthetic fixture"
