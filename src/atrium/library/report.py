# SPDX-License-Identifier: GPL-3.0-or-later
"""What a scan is doing, and what it did.

Two things live here, and they answer two different questions an operator asks. **Progress**
answers "is it still going?" while a scan runs. The **summary** answers "what did it do, and what
did it walk past?" afterwards. Neither reaches a client: 003 has no endpoints, so nothing here is
a wire format and nothing in it can create a delta.

**Three categories, not one**, and keeping them apart is the whole design of this module:

| Category | The file | The item |
|---|---|---|
| Counted — `added`, `updated`, `unchanged`, `removed` | was scanned | exists |
| **Skipped** — `skipped` | was walked past | **does not exist** |
| **Noticed** — `noticed` | was scanned | exists, and is **thin** |
| **Uninspected** — `uninspected` | was **opened, and would not open** | exists, with no streams |

The fourth arrived with 008: 003 said in as many words that a file whose contents cannot be read
is "not detected here … 008 finds it when it goes to probe" (003 plan section 7), and 008 T3 is
where the scan first opens one. It is its own category for the same reason the other three are:
a file that would not open produced an item and is in the library, so counting it as skipped
would send an operator looking for something that is not missing, and counting it as noticed
would say its *name* was the problem.

The task that built this described its job as reporting "an unreadable file and an unparseable
name, each with its reason", which reads like one list with two entries in it. It cannot be: an
unreadable file produced no item and an unparseable name produced one. An operator reading
"2 files skipped" when one of them was in fact scanned and is sitting in their library has been
told something false, and the thing they would do about it - go and look at why those two files
are missing - would waste their time on the one that is not.

**A notice is not an error and not a warning.** It is the scan saying: this file is in your
library, and here is what could not be read from its name, so that when it looks wrong in a client
you know why without having to guess. Plan section 7 calls it "an item with a title and nothing
else".

**`Notice` and `Noticed` are the resolver's**, the way `Skip` and `Skipped` are the walker's. Each
producer owns the vocabulary for what it could not do, and this module only adds them up. The first
version of this file computed the notices here, from the finished items, and **that was wrong**: an
`Episode` with no number is either a file whose name said nothing or a daily show whose episodes
are dated, and an `Item` does not carry a date to tell them apart. Only the thing that read the
name knows.

`Uninspected` is the exception to that rule and says so: its producer is `library/scan.py`, which
imports this module, so it cannot be declared below it without a cycle. The reason - the text a
prober raised - is carried as a string for the same reason `refreshed` is typed `object`: this
module describes a scan and must not depend on 008's exception hierarchy to do it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum

from atrium.library.resolver import Noticed
from atrium.library.walker import Skipped


@dataclass(frozen=True, slots=True)
class Uninspected:
    """One media file that produced an item and would not open, and what the prober said."""

    relative_path: str
    reason: str


# ----------------------------------------------------------------------------------------------
# Progress
# ----------------------------------------------------------------------------------------------


class Phase(StrEnum):
    """The four things a scan does, in the order it does them (003 plan section 6.7).

    `INSPECTING` arrived with 008: opening every changed media file is the slowest thing a scan
    does, and a phase that reported nothing would leave an operator watching "writing 400 of 400"
    for the several minutes a first scan of a large library now takes.
    """

    WALKING = "walking"
    RESOLVING = "resolving"
    INSPECTING = "inspecting"
    WRITING = "writing"


@dataclass(frozen=True, slots=True)
class Progress:
    """One report of how far along a scan is.

    **`total` is `None` when it is not known**, and it is genuinely not known during the walk: how
    many files a tree holds is the answer the walk is computing. A scanner that invented a
    denominator would draw a progress bar that jumps backwards, which is worse than one that says
    it does not know - so `total` counts *roots* during the walk and says so through `detail`.
    """

    library_id: str
    phase: Phase
    done: int
    total: int | None = None
    detail: str = ""

    @property
    def fraction(self) -> float | None:
        """How far through this phase, or None when there is nothing to divide by."""
        if not self.total:
            return None
        return min(1.0, self.done / self.total)


#: Where progress goes. A plain callable rather than an interface: every caller so far wants either
#: nothing or one line of logging, and neither is worth a class to implement.
ProgressSink = Callable[[Progress], None]


def silent(progress: Progress) -> None:
    """The default. A scan run by a test or a migration reports to nobody."""


# ----------------------------------------------------------------------------------------------
# The summary
# ----------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ScanReport:
    """What one scan of one library did.

    Carried `removed` from T15, before this module could make it non-zero, so that T16's threshold
    and T17's removals would report into one type rather than each inventing half of one.
    """

    library_id: str
    added: int = 0
    updated: int = 0
    unchanged: int = 0

    examined: int = 0
    """Candidate files whose `(size, mtime_ns)` had moved, so this scan looked at them again
    rather than keeping the row it already had.

    Every other candidate was skipped by the signal (plan section 6.4). Looking at a file means
    asking the metadata seam what is inside it, which only a music library does - so a `movies`
    scan can report a non-zero `examined` having opened nothing. It is a count of what was *not
    trusted*, not of what was read.

    Under `deep` this is every candidate, which is the whole of what `deep` means.
    """

    removed: int = 0
    """Items whose files are gone, marked `removed_at`. **Soft**: the row stays and so does the
    user data keyed to its identifier (spec section 3.8)."""

    revived: int = 0
    """Items whose files came back, brought out of removal **with the same identifier**."""

    missing: int = 0
    """Items in the database whose files are no longer on disk.

    The same number as `removed` in an ordinary scan; it stays a separate field because guard
    three counts it *before* deciding whether to act, and a scan that refuses reports a `missing`
    with a `removed` of zero.
    """

    skipped: tuple[Skipped, ...] = field(default_factory=tuple)
    """Every file the walk went past, each with its reason (plan section 7). **These produced no
    item.** See the module docstring for why they are not in the same list as `noticed`."""

    noticed: tuple[Noticed, ...] = field(default_factory=tuple)
    """Every file that *did* produce an item, and what could not be read from its name."""

    inspected: int = 0
    """Media files this scan opened, because what was stored about their bytes no longer described
    them - or because nothing was stored at all.

    Separate from `examined`, and the difference is which question was asked. `examined` counts the
    files whose *tags* the scan did not trust; this counts the files whose *inspection* it did not
    trust, against the probe rows rather than against `item_sources`. The two disagree on the first
    scan after 008 arrived, when every file has an unchanged signal and no inspection at all.
    """

    uninspected: tuple[Uninspected, ...] = field(default_factory=tuple)
    """Every file this scan opened and could not read, with the reason the prober gave.

    **These produced items.** A file that will not open still has a name, a path and an identity;
    what it does not have is a container, a duration or any streams, so a client sees the item and
    cannot play it. See the module docstring for why that is not the same list as `skipped`.
    """

    refreshed: object | None = None
    """What 004's refresh did to the items this scan touched, or `None` when it did not run.

    Typed as `object` on purpose: `report.py` is 003's and describes a scan, and giving it a
    `RefreshReport` field would make `library/` depend on `metadata/`'s *types* as well as its
    behaviour. A caller that wants the detail knows what it asked for.
    """

    @property
    def changed(self) -> int:
        return self.added + self.updated

    def reasons(self) -> dict[str, int]:
        """How many files each skip reason accounted for."""
        counts: dict[str, int] = {}
        for one in self.skipped:
            counts[one.reason.value] = counts.get(one.reason.value, 0) + 1
        return counts

    def notice_reasons(self) -> dict[str, int]:
        """The same, for the files that were scanned rather than skipped."""
        counts: dict[str, int] = {}
        for one in self.noticed:
            counts[one.reason.value] = counts.get(one.reason.value, 0) + 1
        return counts

    def summary(self) -> str:
        """One line, for an operator or a log.

        Skipped and noticed are named separately and always printed, including at zero: a summary
        that omits a category when it is empty makes "no files were skipped" indistinguishable
        from "this version does not report skipped files".
        """
        return (
            f"library {self.library_id}: {self.added} added, {self.updated} updated, "
            f"{self.unchanged} unchanged, {self.removed} removed, {self.revived} revived; "
            f"{self.examined} re-examined, {self.inspected} inspected; "
            f"{len(self.skipped)} skipped, {len(self.noticed)} noticed, "
            f"{len(self.uninspected)} uninspected"
        )


__all__ = [
    "Phase",
    "Progress",
    "ProgressSink",
    "ScanReport",
    "Uninspected",
    "silent",
]
