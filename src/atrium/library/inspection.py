# SPDX-License-Identifier: GPL-3.0-or-later
"""Opening one file, inside one request, because a negotiation is about to need what is in it.

The on-demand half of 003's inspection. `library/scan.py` opens every file in a library and stores
what it finds; this module opens **one**, for the one request that discovered nothing was stored,
and hands the answer to the same repository (012 spec section 3.2).

**The trigger is the reference's condition, not the shape of the defect.** What a client reports is
"a source nobody ever inspected"; what the reference actually asks is whether *source zero* carries
a stream of the **item's own kind** `[source:
Emby.Server.Implementations/Library/MediaSourceManager.cs:174-178 @ v10.11.11]`. The two are not
the same question, and the difference is visible from both sides: a file that was inspected
successfully and holds no stream of its item's kind - a film with no video track, a track with no
audio - satisfies the reference's condition and is re-opened on **every** negotiation for ever,
while a second part with no inspection at all does not satisfy it and is never opened by this path.
`wanted` is written to the condition, so both of those follow rather than being decided here.

**Nothing here writes except `store`, and `store` never receives what `unopened` produced.** The
transient inspection carries the *source row's* own change signal, so a stored one would satisfy
`MediaProbeRepository.current()` against the file's real stat and the next scan would skip the file
for ever - a library nothing can play, curable only by a deep scan (012 plan section 5, invariant
1). `unopened` exists so the ladder has something with no streams in it to decide against, and for
nothing else.

See specs/012-negotiation-inputs/plan.md sections 5 and 6.1.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from sqlalchemy.orm import Session as OrmSession

from atrium.compat.dates import utc_now
from atrium.db.repositories import ItemRepository, MediaProbeRepository
from atrium.domain.items import MediaSource
from atrium.domain.media import MediaInspection, StreamKind
from atrium.library.scan import MediaProber
from atrium.media.probe import InspectionError, inspect

#: The extension whose presence opens a file whatever its streams say. Written, unreachable and
#: cited rather than dropped: no library extension 003 admits is `.strm`, so nothing in v1 can be
#: one - and a later reader learning the condition from this module should learn all of it
#: `[source: Emby.Server.Implementations/Library/MediaSourceManager.cs:176 @ v10.11.11]`.
STREAM_DESCRIPTOR_SUFFIX = ".strm"

#: What `unopened` puts where a container string would be. Empty rather than the file's extension,
#: because `media/info.py:source_container` falls back to the extension for exactly this - so the
#: wire shape is the one a source with no inspection at all already answers - and because it is
#: what tells a transient inspection from a real one: `media/probe.py:inspect` refuses a file whose
#: container has no name, so no inspection it returns can carry this.
UNOPENED_CONTAINER = ""


def wanted(
    sources: Sequence[MediaSource],
    inspections: Sequence[MediaInspection | None],
    *,
    is_video: bool,
) -> bool:
    """Whether this item's files must be opened before a profile is applied.

    The reference's condition exactly: source **zero** carries no stream of the item's own kind, or
    its path ends `.strm` - which is source zero's path here, an item's own `Path` being that
    file's on the reference too. A property of *the item*, answered once, and not a filter over
    parts `[source: Emby.Server.Implementations/Library/MediaSourceManager.cs:174-178 @
    v10.11.11]`.

    `inspections` is positional against `sources`, the way `media/info.py:sources_for` reads it: a
    short sequence means the parts past its end were never inspected.

    **A missing inspection is a special case of the condition and not the condition**, which is the
    whole reason this is not "is this part inspected". A source zero holding no stream of the
    item's kind fires this whether it was inspected or not, and answers the same on the next
    request and every one after it, because nothing about the file will have changed.

    **The reference's condition has a fourth clause that is a gate rather than a trigger**, and it
    is recorded here rather than written: it declines to probe when source zero is a *placeholder*,
    which is an active recording or a source with no path at all `[source:
    MediaBrowser.Controller/Entities/BaseItem.cs:1103, 1159 @ v10.11.11]`. v1 has no live
    television, and `MediaSource.relative_path` is required and comes from a file the walk statted,
    so neither shape exists here to be gated.
    """
    if not sources:
        return False
    if sources[0].relative_path.lower().endswith(STREAM_DESCRIPTOR_SUFFIX):
        return True
    found = inspections[0] if inspections else None
    if found is None:
        return True
    kind = StreamKind.VIDEO if is_video else StreamKind.AUDIO
    return all(one.kind is not kind for one in found.streams)


def opened(path: Path, prober: MediaProber = inspect) -> MediaInspection | None:
    """Open one file now, or `None` when it cannot be opened. Never raises.

    Touches no session and no ORM object, because it is what the route runs in a thread (012 plan
    section 6.2).

    **Both inspection failures come back as `None`, on purpose.** `ProberUnavailableError` and
    `UnreadableMediaError` mean opposite things to a scan - one file that will not open is a fact
    about that file, and a prober that is not installed is a fact about every file at once - and
    the same thing to one request, which can act on neither. `library/scan.py` keeps the
    distinction where it decides something (003 section 3.7): there the second stops the phase and
    is logged as the operator's problem it is.
    """
    try:
        return prober(path)
    except InspectionError:
        return None


def store(
    session: OrmSession,
    item_id: str,
    part_index: int,
    library_id: str,
    relative_path: str,
    found: MediaInspection,
) -> None:
    """Write one inspection through the scan's own repository, and the file's change signal.

    Two rows: the `(size, mtime_ns)` of that one part, in place, through a narrowly-scoped method
    on `ItemRepository` (012 plan section 4, D-1), and the inspection itself through
    `MediaProbeRepository.put`, whose streams are deleted and rewritten rather than merged. The
    two come from one `stat()`, taken inside the inspection, so writing one without the other
    would put a tag and a size on the wire that describe different bytes:
    `media/info.py:source_of` takes `Size` from the inspection and `ETag` from the source row.

    **The change signal goes first, and the order is the argument for the check inside it.**
    `record_change_signal` is the call that can refuse - a part that is not there, or one naming
    another file - and a refusal before `put` leaves *neither* row written rather than a probe row
    whose signal was never updated, which is the exact half-healed state D-1 exists to prevent.
    Both writes are the request's transaction either way (`db/engine.py:session_scope`), so a
    caller that swallowed the exception is the only case the order decides - and that is the case
    worth deciding.

    **It refuses what `unopened` produced, and the check is the container** (012 plan section 5,
    invariant 1). The transient record carries the *source row's* own change signal, so storing
    one would satisfy `MediaProbeRepository.current()` against the file's real stat and the next
    scan would skip the file for ever - a library nothing can play, curable only by a deep scan.
    `media/probe.py:inspect` refuses a file whose container has no name, so an empty container
    tells the two apart with no flag to carry and no reviewer to remember.
    """
    if found.container == UNOPENED_CONTAINER:
        raise ValueError(
            f"{relative_path!r}: this is the transient inspection `unopened` builds, not one any "
            f"file produced. Storing it would satisfy the next scan's change comparison and the "
            f"file would never be opened again (012 plan section 5, invariant 1)."
        )
    ItemRepository(session).record_change_signal(
        item_id, part_index, relative_path, size=found.size, mtime_ns=found.mtime_ns
    )
    MediaProbeRepository(session).put(library_id, relative_path, found)


def unopened(part: MediaSource) -> MediaInspection:
    """The transient inspection a file that would not open is negotiated against.

    Size and change signal from the stored source row, an empty container - so
    `media/info.py:source_container` still answers the file's extension - no runtime, no bitrate,
    no streams. **Never stored** (see the module docstring). It exists so the ladder can decide the
    three capability flags for a source with nothing in it, which is what the reference's answer
    carries (012 AC-1).

    Put through `media/info.py:source_of` it serialises to exactly what a `None` inspection
    serialises to today, which is what keeps AC-10 true: this feature changes what a *negotiation*
    decides and nothing about what a listing says. The one part that cannot answer identically is
    one whose row carries no size - `Size: 0` here against `Size: null` there - and no scan
    produces one: `library/walker.py`'s `Candidate.size` is an integer taken from a `stat()`, and
    it is the only thing that ever fills that column.
    """
    return MediaInspection(
        size=0 if part.size is None else part.size,
        mtime_ns=0 if part.mtime_ns is None else part.mtime_ns,
        container=UNOPENED_CONTAINER,
        format_names=UNOPENED_CONTAINER,
        probed_at=utc_now(),
    )


__all__ = [
    "STREAM_DESCRIPTOR_SUFFIX",
    "UNOPENED_CONTAINER",
    "opened",
    "store",
    "unopened",
    "wanted",
]
