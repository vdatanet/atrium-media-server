# SPDX-License-Identifier: GPL-3.0-or-later
"""The three criteria that need the whole stack, and the one that needs a real scan.

**AC-2** is the tag's contract: unchanged across a rescan when the bytes are, changed when they
are not. It is the only place in feature 006 where a scan runs — every other test seeds through
the repositories, which is 005's discipline and 003's proof that the scan works. Here the scan
*is* the subject: the tag is what makes a client's cached poster valid, and a tag that churned on
every rescan would re-fetch every image in a library while looking perfectly correct.

**AC-8** and **AC-13** are the two halves of "the cache is an optimisation and never an answer":
a hit is byte-identical to the miss that filled it, and deleting the whole tree costs a recompute.
The honest version of AC-8 is not "ask twice" — that passes against a server with no cache at all.
It is *overwrite the source file without rescanning and ask again*: the row still names the old
content, so the old bytes are the right answer, and a reply that had recomputed would be visibly
different.

And the loop closes where spec §3.4 says it does: a **rescan** after that overwrite gives the row
a new tag, the next request serves the new bytes, and the old cache entry becomes garbage nobody
can address — asserted by the key being absent rather than by the file being deleted, because
nothing deletes it.
"""

from __future__ import annotations

import io
import os
import shutil
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from PIL import Image
from sqlalchemy import select

from atrium.config.paths import DataPaths
from atrium.db import models
from atrium.db.engine import session_scope
from atrium.db.repositories import LibraryRepository
from atrium.domain.library import Library
from atrium.images.cache import DIRECTORY, key_for
from atrium.images.transform import Source, TransformSpec, decide
from atrium.library import config
from atrium.library.scan import scan
from atrium.server import create_app
from tests.conftest import data_dir, not_media
from tests.fixtures.images import POSTER_SIZE, draw

pytestmark = pytest.mark.conformance

#: The film the scan finds, and the poster beside it. Named `poster.jpg` because that is the
#: first name 004's Primary table tries for a film.
FILM = "The Scanned One"
POSTER = "poster.jpg"

#: A second drawing, of a different size, so "the bytes changed" is visible in the tag *and* in
#: what a client receives.
REPLACEMENT_SIZE = (800, 1200)


@pytest.fixture
def paths(tmp_path: Path) -> DataPaths:
    return data_dir(tmp_path / "atrium")


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A library on disk, with one film and one poster."""
    folder = tmp_path / "films" / FILM
    folder.mkdir(parents=True)
    (folder / f"{FILM}.mkv").write_bytes(b"atrium synthetic fixture - not media\n" + b"\0" * 600)
    (folder / POSTER).write_bytes(draw(*POSTER_SIZE, "JPEG"))
    return tmp_path / "films"


@pytest.fixture
def app(paths: DataPaths, root: Path) -> Iterator[FastAPI]:
    built = create_app(paths)
    built.state.readiness.mark_ready()
    yield built
    built.state.db.dispose()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://atrium:8096") as opened:
        yield opened


@pytest.fixture
def library(app: FastAPI, root: Path) -> Library:
    with session_scope(app.state.sessions) as opened:
        return config.create(LibraryRepository(opened), "Films", "movies", (str(root),))


def rescan(app: FastAPI, library: Library, *, deep: bool = False) -> None:
    with session_scope(app.state.sessions) as opened:
        scan(library, opened, deep=deep, prober=not_media)


def the_film(app: FastAPI) -> models.Item:
    with session_scope(app.state.sessions) as opened:
        rows = list(opened.execute(select(models.Item)).scalars())
    found = [row for row in rows if row.type == "Movie"]
    assert len(found) == 1, [row.name for row in rows]
    return found[0]


def the_tag(app: FastAPI) -> str:
    with session_scope(app.state.sessions) as opened:
        rows = list(opened.execute(select(models.ItemImage)).scalars())
    assert len(rows) == 1, "the fixture has exactly one image"
    return rows[0].tag


def decoded(payload: bytes) -> Image.Image:
    return Image.open(io.BytesIO(payload))


def cache_entries(paths: DataPaths) -> list[Path]:
    root = paths.cache / DIRECTORY
    return sorted(path for path in root.rglob("*") if path.is_file()) if root.exists() else []


# ------------------------------------------------------------------------------------------
# AC-2: the tag changes when the image does, and only then
# ------------------------------------------------------------------------------------------


def test_ac2_a_touch_that_changes_no_bytes_changes_no_tag(
    app: FastAPI, library: Library, root: Path
) -> None:
    """The half that matters most for a client: a rescan of an unchanged library must not
    invalidate a single cached poster.

    The mtime is moved deliberately, because that is 003's change-detection signal — so this scan
    *does* re-examine the file, and the tag still has to come out the same. A tag derived from a
    timestamp or a row id would pass every other test in this feature and fail here.
    """
    rescan(app, library)
    first = the_tag(app)

    poster = root / FILM / POSTER
    stamp = poster.stat().st_mtime_ns + 5_000_000_000
    os.utime(poster, ns=(stamp, stamp))
    rescan(app, library)

    assert the_tag(app) == first


def test_ac2_changing_the_bytes_changes_the_tag(app: FastAPI, library: Library, root: Path) -> None:
    """AC-2's second half. `deep=True` because 003's change detection keys on the **media file**
    and replacing a poster touches neither its size nor its mtime — see
    `test_a_default_rescan_does_not_notice_an_artwork_only_change` below, which pins that.

    This half was unreachable at any depth until this task: `Field.IMAGES` merged under the rule
    that keeps what an item already has, so an item that had ever been given artwork could never
    be given different artwork, and v1 has no refresh route through which anybody could ask for
    `Replace`.
    """
    rescan(app, library)
    first = the_tag(app)

    (root / FILM / POSTER).write_bytes(draw(*REPLACEMENT_SIZE, "JPEG"))
    rescan(app, library, deep=True)

    assert the_tag(app) != first


def test_the_tag_is_the_content_hash_and_not_something_weaker(
    app: FastAPI, library: Library, root: Path
) -> None:
    """Asserted against the hash itself: OQ-1 measured that the *reference's* tags are something
    weaker than a content hash, and Atrium's are the stronger thing on purpose (spec §3.1). A
    client cannot tell, and every cache guarantee in this feature rests on it."""
    from atrium.metadata.artwork import tag_of

    rescan(app, library)

    assert the_tag(app) == tag_of((root / FILM / POSTER).read_bytes())


# ------------------------------------------------------------------------------------------
# AC-8: a hit is the image the row names, not the file on disk
# ------------------------------------------------------------------------------------------


async def test_ac8_the_same_request_twice_is_byte_identical(
    client: httpx.AsyncClient, app: FastAPI, library: Library
) -> None:
    rescan(app, library)
    path = f"/Items/{the_film(app).id}/Images/Primary"

    first = await client.get(path, params={"maxWidth": "300"})
    second = await client.get(path, params={"maxWidth": "300"})

    assert first.status_code == 200
    assert second.content == first.content


async def test_ac8_a_hit_never_recomputes_even_after_the_file_changes(
    client: httpx.AsyncClient, app: FastAPI, library: Library, root: Path
) -> None:
    """Overwritten **without rescanning**: the row still names the old content, so the old bytes
    are the right answer. A server that recomputed on every request would answer the replacement's
    size here and pass a test that only asked twice."""
    rescan(app, library)
    path = f"/Items/{the_film(app).id}/Images/Primary"
    first = await client.get(path, params={"maxWidth": "300"})

    (root / FILM / POSTER).write_bytes(draw(*REPLACEMENT_SIZE, "JPEG"))
    again = await client.get(path, params={"maxWidth": "300"})

    assert again.content == first.content


async def test_a_rescan_after_that_overwrite_serves_the_new_bytes(
    client: httpx.AsyncClient, app: FastAPI, library: Library, root: Path, paths: DataPaths
) -> None:
    """The loop spec §3.4 promises, closed: a new tag means a new key, the new bytes are served,
    and the old entry becomes garbage **nobody can address**.

    Asserted by the old key being absent from what any request can now ask for — not by the file
    being deleted, because nothing deletes it. That is the whole design: eviction is an operator's
    `rm`, and correctness never depended on it.
    """
    rescan(app, library)
    item = the_film(app).id
    path = f"/Items/{item}/Images/Primary"
    before = await client.get(path, params={"maxWidth": "300"})
    stale_key = _key_for(item, the_tag(app))

    (root / FILM / POSTER).write_bytes(draw(*REPLACEMENT_SIZE, "JPEG"))
    rescan(app, library, deep=True)
    after = await client.get(path, params={"maxWidth": "300"})
    fresh_key = _key_for(item, the_tag(app))

    assert after.content != before.content
    assert decoded(after.content).size == (300, 450)
    assert stale_key.digest != fresh_key.digest, "a changed tag is a changed key"
    assert (paths.cache / DIRECTORY / stale_key.relative).is_file(), "still there, and unreachable"
    assert (paths.cache / DIRECTORY / fresh_key.relative).is_file()


def _key_for(item_id: str, tag: str) -> object:
    """The key a `maxWidth=300` request of this poster computes — built from the same values the
    service builds it from, so the test cannot agree with itself by construction."""
    source = Source(
        width=POSTER_SIZE[0], height=POSTER_SIZE[1], image_format="JPEG", has_alpha=False
    )
    return key_for(
        item_id=item_id,
        image_type="Primary",
        index=0,
        tag=tag,
        decision=decide(TransformSpec(max_width=300), source),
    )


async def test_a_default_rescan_does_not_notice_an_artwork_only_change(
    client: httpx.AsyncClient, app: FastAPI, library: Library, root: Path
) -> None:
    """The limitation the two tests above take `deep=True` to work around, pinned rather than
    left to be rediscovered.

    003's change-detection signal is the **media file's** size and modification time (003 plan
    §6.4), and replacing a poster touches neither — so a default scan does not re-examine the
    item and the tag stands. A client therefore keeps a replaced poster until a deep scan runs.
    Recorded in [behaviours §5.6](../../docs/compatibility/behaviours.md); widening the signal
    would mean stat-ing every candidate artwork name of every item on every scan, which is the
    cost 003's design exists to avoid.

    This is the test that fails the day that changes — at which point the two above can drop
    their `deep=True` and this one is deleted.
    """
    rescan(app, library)
    first = the_tag(app)

    (root / FILM / POSTER).write_bytes(draw(*REPLACEMENT_SIZE, "JPEG"))
    rescan(app, library)

    assert the_tag(app) == first, "a default scan does not look at artwork of an unchanged item"


# ------------------------------------------------------------------------------------------
# AC-13: deleting the cache costs time and nothing else
# ------------------------------------------------------------------------------------------


async def test_ac13_deleting_the_whole_cache_changes_no_response_body(
    client: httpx.AsyncClient, app: FastAPI, library: Library, paths: DataPaths
) -> None:
    rescan(app, library)
    path = f"/Items/{the_film(app).id}/Images/Primary"
    first = await client.get(path, params={"maxWidth": "300"})
    assert cache_entries(paths), "the first request filled it"

    shutil.rmtree(paths.cache / DIRECTORY)
    recomputed = await client.get(path, params={"maxWidth": "300"})

    assert recomputed.content == first.content
    assert recomputed.headers["content-type"] == first.headers["content-type"]
    assert cache_entries(paths), "and it wrote itself back"


async def test_the_verbatim_path_needs_no_cache_at_all(
    client: httpx.AsyncClient, app: FastAPI, library: Library, paths: DataPaths
) -> None:
    """Which is why AC-8 and AC-13 are trivial for most requests: an untransformed reply is the
    file, and there is nothing to cache that the file is not already (plan §1)."""
    rescan(app, library)

    answered = await client.get(f"/Items/{the_film(app).id}/Images/Primary")

    assert answered.status_code == 200
    assert not cache_entries(paths)
