# SPDX-License-Identifier: GPL-3.0-or-later
"""The one operation that actually deletes, kept where a scan cannot reach it.

A removed item keeps its row (003 plan section 6.6): the file is gone, `removed_at` says when, and
everything a user did with that item is still keyed to an identifier that will derive again the
moment the file comes back. That is the whole of why a re-download or a slow mount costs nobody
their favourites.

**Purging is therefore an operator's decision, not a scan's.** It lives in its own module, and a
test asserts that `library/scan.py` does not import this one — the same shape argument as
`ItemRepository` having no delete method before T16: a scan that merely *chose* not to purge would
be one refactor away from purging.

What is lost by purging is not the row. It is the **association**: user data is keyed by the
derived identity and outlives the item, so purging an item does not delete anybody's favourites -
it only removes the thing they pointed at. If that file ever returns, the association returns with
it. Purging is therefore reversible in the only sense that matters, which is why it is allowed to
exist at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session as OrmSession

from atrium.compat.dates import utc_now
from atrium.db import models
from atrium.domain.library import Library

#: How long a removed item is kept before an unqualified purge will touch it.
#:
#: Thirty days rather than none. The failure this protects against is an operator running a purge
#: to tidy up on the same afternoon a share was slow to mount - at which point the rows are gone
#: and the next scan re-adds them with the same identifiers but no history of ever having been
#: away. The grace period costs a few rows and buys the time to notice.
DEFAULT_GRACE = timedelta(days=30)


@dataclass(frozen=True, slots=True)
class PurgeReport:
    library_id: str
    purged: int = 0
    kept: int = 0
    """Removed items still inside the grace period, which this purge left alone."""


def purge_removed(
    library: Library,
    session: OrmSession,
    *,
    grace: timedelta = DEFAULT_GRACE,
    now: datetime | None = None,
) -> PurgeReport:
    """Delete the rows of items whose files have been gone for longer than `grace`.

    Writes inside the caller's transaction and never commits, like `scan`.

    Passing `grace=timedelta(0)` purges everything currently marked removed, which is what an
    operator who has just cleared out a library on purpose wants and what nobody should get by
    accident.
    """
    cutoff = (now or utc_now()) - grace
    removed = list(
        session.execute(
            select(models.Item.id, models.Item.removed_at).where(
                models.Item.library_id == library.id, models.Item.removed_at.is_not(None)
            )
        )
    )
    stale = [
        item_id
        for item_id, removed_at in removed
        if removed_at is not None and removed_at <= cutoff
    ]

    if stale:
        session.execute(delete(models.Item).where(models.Item.id.in_(stale)))
        session.flush()

    return PurgeReport(library_id=library.id, purged=len(stale), kept=len(removed) - len(stale))


__all__ = ["DEFAULT_GRACE", "PurgeReport", "purge_removed"]
