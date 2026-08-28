# SPDX-License-Identifier: GPL-3.0-or-later
"""Precedence, locks and refresh modes: the whole of what wins, as a pure function.

Values in, values out. No database, no files, no network - which is what makes the matrix below a
table of plain values rather than an integration suite (plan section 3), and it matters because
this is where a metadata feature's subtle bugs live. A merge that quietly overwrites a user's
correction is discovered months later, by a user who has stopped correcting things.

**Two ideas, and keeping them apart is the whole design.** *Precedence* is the ordered chain of
sources: for each field, the first source with a value for it wins, and a source with nothing to
say about a field cannot blank it. *Mode* is what happens between that winner and what the item
already has. The first is per field and knows nothing about the item; the second is per field and
knows nothing about the chain.

| | field locked | field empty on item | field has a value |
|---|---|---|---|
| **Default** | keep | fill | keep |
| **Replace** | keep | fill | overwrite |
| **Local only** | keep | fill, from local sources only | keep |

**Three things the reference does that plan section 6.1 did not**, all measured from its own merge
`[source: MediaBrowser.Providers/Manager/MetadataService.cs:1009-1200 @ v10.11.11]` and none of
them reachable by reasoning:

* **A lock is coarser than a field.** Nine `MetadataField` values guard twenty-one fields, eight
  of them guarding exactly one each and thirteen fields not lockable at all. `LOCK_OF` is the map.
* **List fields do not share one rule.** `Genres` is taken whole from one source; `Studios` and
  `Tags` are **unioned** with what the item already has; `People` has existing entries *enriched*
  without any being added; `ProviderIds` accumulates key by key. Plan section 10 rejected
  union-merging on reasoning that is sound and was not ours to apply - Principle I says reproduce.
* **A runtime from metadata is discarded for a file-backed item.** A film's runtime comes from
  probing the file, so an `.nfo` saying `97` changes nothing about a film in the reference, and
  honouring it here would give Atrium's films a runtime the reference's do not have.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from atrium.domain.items import FILE_BACKED, ItemType
from atrium.metadata.model import (
    LOCK_OF,
    Field,
    FieldValues,
    MetadataField,
    PersonCredit,
    RefreshMode,
    is_value,
)


class SourceKind(StrEnum):
    """Where an answer came from, which is all the chain needs to know about it.

    `LOCAL` and `REMOTE` is the distinction `RefreshMode.LOCAL_ONLY` turns on; the rest is
    ordering, and the ordering is `CHAIN_OF`.
    """

    NFO = "nfo"
    TAGS = "tags"
    PATH = "path"
    REMOTE = "remote"

    @property
    def is_local(self) -> bool:
        return self is not SourceKind.REMOTE


#: Spec section 3.1's table, as data. Position 1 of that table - locked fields - is not a source
#: and is not here: a lock does not *supply* a value, it forbids one, which `merge` applies
#: separately.
#:
#: **Music inverts the first two on purpose.** A music file carries its own metadata and a video
#: file almost never does, so reading a well-tagged FLAC and then overwriting its album name with a
#: guess from the directory would be a regression a user notices immediately.
#:
#: **`PATH` appears twice in the film chain because the spec's table lists it twice**, at positions
#: 3 and 5. In a first-value-wins walk a repeated source is a no-op - the second occurrence can
#: only win a field the first already lost - so this reproduces the table exactly and behaves as
#: though it did not. It is left visible rather than tidied away because the two readings of that
#: table differ in one observable way, recorded in plan section 6.1 for T14 to settle: with `PATH`
#: before `REMOTE`, a `Replace` refresh cannot take a film's *name* from TMDB.
CHAIN_OF: Mapping[ItemType, tuple[SourceKind, ...]] = {
    ItemType.MOVIE: (SourceKind.NFO, SourceKind.PATH, SourceKind.REMOTE, SourceKind.PATH),
    ItemType.SERIES: (SourceKind.NFO, SourceKind.PATH, SourceKind.REMOTE, SourceKind.PATH),
    ItemType.SEASON: (SourceKind.NFO, SourceKind.PATH, SourceKind.REMOTE, SourceKind.PATH),
    ItemType.EPISODE: (SourceKind.NFO, SourceKind.PATH, SourceKind.REMOTE, SourceKind.PATH),
    ItemType.AUDIO: (SourceKind.TAGS, SourceKind.NFO, SourceKind.REMOTE, SourceKind.PATH),
    ItemType.MUSIC_ALBUM: (SourceKind.TAGS, SourceKind.NFO, SourceKind.REMOTE, SourceKind.PATH),
    ItemType.MUSIC_ARTIST: (SourceKind.TAGS, SourceKind.NFO, SourceKind.REMOTE, SourceKind.PATH),
}


class ListRule(StrEnum):
    """How a field with several values combines with what the item already has.

    One rule per field rather than one rule for lists, because the reference does not have one
    rule for lists - and a client reads the difference.
    """

    WHOLE = "taken whole from one source, never unioned"
    UNION = "added to what the item already has, case-insensitively distinct"
    ENRICH = "existing entries filled in; none added, none removed"
    ACCUMULATE = "key by key; a key the item already has is not replaced"
    REDERIVED = "re-read from its one source every time, whatever the item already has"


#: The rule for each field that has one. Anything absent is a scalar: one value, replaced or kept.
#:
#: `WHOLE` for `GENRES` is plan section 6.1's argument and the reference's behaviour at once - a
#: sidecar naming two genres and TMDB naming five is a film with two genres, and a union produces
#: a list no single source wrote and no user can correct by fixing any one file.
#:
#: `UNION` for `STUDIOS` and `TAGS` is the reference's and **not** what plan section 10 argued for.
#: The argument above is sound and was not ours to apply: Principle I says reproduce.
#:
#: **`IMAGES` is `REDERIVED`, and it was `WHOLE` until 006 T12.** Under `WHOLE` it went through the
#: scalar branch below, which keeps what the item already has unless the mode is `Replace` - so an
#: item that had ever been given artwork could never be given different artwork. That is right for
#: a *value* somebody may have curated and wrong for this field: `IMAGES` has exactly **one**
#: source, the directory walk, so "keep what we have" is not protecting a better answer from a
#: worse one - it is protecting a stale index of the directory from the directory. The consequence
#: was 006 AC-2 being unreachable: replacing a poster changed no tag, ever, under any scan, and v1
#: has no refresh route through which anybody could have asked for `Replace`. The tag is the whole
#: of client-side cache invalidation (006 spec section 3.1), so a tag that cannot change is a
#: poster that can never be corrected.
LIST_RULE: Mapping[Field, ListRule] = {
    Field.GENRES: ListRule.WHOLE,
    Field.ARTISTS: ListRule.WHOLE,
    Field.ALBUM_ARTISTS: ListRule.WHOLE,
    Field.IMAGES: ListRule.REDERIVED,
    Field.STUDIOS: ListRule.UNION,
    Field.TAGS: ListRule.UNION,
    Field.PEOPLE: ListRule.ENRICH,
    Field.PROVIDER_IDS: ListRule.ACCUMULATE,
}


@dataclass(frozen=True, slots=True)
class Source:
    """One source's answer about one item.

    `values` is a `FieldValues`: an absent key means *nothing to say about that field*, which is
    what lets a source be consulted for one field and skipped for the next without a special case.
    """

    kind: SourceKind
    values: FieldValues = field(default_factory=dict)
    name: str = ""
    """For the report and for tests: `Tmdb`, `movie.nfo`, `tags`. Never used for precedence."""


@dataclass(frozen=True, slots=True)
class Current:
    """The item as it currently stands, and what may not be changed about it.

    **Not `model.Subject`**, which is a different thing with a confusingly similar name: that one
    is what a *provider is told* about an item so it can identify it - a name, a year, some ids.
    This one is what the item *already has*. They met in `refresh.py` and the collision was worth
    a rename rather than an alias.
    """

    kind: ItemType
    values: FieldValues = field(default_factory=dict)
    """What a **previous refresh** resolved. This is what the mode's "field empty on item" column
    asks about, and it deliberately excludes the fields 003's scanner owns - a name derived from a
    filename is not a value a default refresh must preserve, or AC-1 could not hold."""

    stored: FieldValues = field(default_factory=dict)
    """What is **physically on the row**, scanner-owned fields included.

    Used for one thing and nothing else: deciding that a settled value is already the stored one,
    so nothing is written. Without it a name excluded from `values` looks empty every time and is
    rewritten on every refresh, and "a rescan of an unchanged library changes nothing" becomes
    false in a way no engine-level test can see.
    """

    locked_fields: frozenset[MetadataField] = frozenset()
    is_locked: bool = False


@dataclass(frozen=True, slots=True)
class MetadataChanges:
    """Only what changes, and why nothing else did.

    Empty when a refresh found nothing to do, which is the common case on a rescan and the reason
    the write path can skip an item entirely rather than rewriting it with its own values.
    """

    values: Mapping[Field, object] = field(default_factory=dict)

    refused: frozenset[Field] = frozenset()
    """Fields a source had a value for that a lock forbade changing.

    Kept because it is the difference between "no provider had anything" and "a provider had
    something and was told no" - and the second is what AC-10 is about.
    """

    def __bool__(self) -> bool:
        return bool(self.values)


def merge(subject: Current, sources: Sequence[Source], mode: RefreshMode) -> MetadataChanges:
    """What this refresh changes about `subject`.

    `sources` is already in precedence order; this function does not sort it. Plan section 6.1
    puts that order in the caller and `CHAIN_OF` puts it in data, so the only branching here is on
    the *mode* and on the *field*, never on which provider is speaking.
    """
    if subject.is_locked:
        # `<lockdata>true</lockdata>`: nothing about this item may change, whatever the mode. Every
        # field a source offered is refused rather than silently absent, so the report can say so.
        return MetadataChanges(refused=frozenset(_offered(sources)))

    usable = [
        source for source in sources if mode.consults_remote_providers or source.kind.is_local
    ]
    changes: dict[Field, object] = {}
    refused: set[Field] = set()

    for candidate in _offered(usable):
        winner = _first_value(usable, candidate)
        if winner is None:
            continue
        if _is_locked(subject, candidate):
            refused.add(candidate)
            continue
        if not _applies_to(candidate, subject.kind):
            continue
        settled = _apply(candidate, subject.values.get(candidate), winner, mode)
        if settled is _UNCHANGED:
            continue
        if candidate in subject.stored and settled == subject.stored[candidate]:
            # Already what the row says. Writing it again would touch every item on every refresh.
            continue
        changes[candidate] = settled

    return MetadataChanges(values=changes, refused=frozenset(refused))


# ----------------------------------------------------------------------------------------------
# The chain
# ----------------------------------------------------------------------------------------------


def _offered(sources: Iterable[Source]) -> list[Field]:
    """Every field any source spoke about, in the order they were first spoken about.

    Order matters only for reproducible output; the merge itself is per field and independent.
    """
    seen: dict[Field, None] = {}
    for source in sources:
        for key in source.values:
            seen.setdefault(key, None)
    return list(seen)


def _first_value(sources: Sequence[Source], key: Field) -> object | None:
    """The first source with an actual value for `key`.

    "A provider that returns nothing for a field does not blank it; only a provider that returns a
    *value* sets it" (spec section 3.1). Empty string, empty list and whitespace are not values,
    so a sparse sidecar cannot erase what a later source knows.
    """
    for source in sources:
        found = source.values.get(key)
        if is_value(found):
            return found
    return None


def _is_locked(subject: Current, key: Field) -> bool:
    """Whether a lock forbids changing `key`.

    Through `LOCK_OF`, because a lock names one of the reference's nine coarse fields and this
    names one of twenty-one. Thirteen fields have no lock at all - the original title among them,
    which the reference overwrites on the line after the name lock.
    """
    guard = LOCK_OF.get(key)
    return guard is not None and guard in subject.locked_fields


def _applies_to(key: Field, kind: ItemType) -> bool:
    """Whether this field may be set on this type at all.

    One rule today, and it is the reference's: **a runtime from metadata is ignored for a
    file-backed item**, because a film's or a track's runtime comes from probing the file
    `[source: MediaBrowser.Providers/Manager/MetadataService.cs:1102-1112 @ v10.11.11]`. Honouring
    an `.nfo` `<runtime>` on a film would give Atrium a duration the reference does not report -
    visible, because 004 has no prober and the reference's value comes from one.
    """
    return not (key is Field.RUNTIME and kind in FILE_BACKED)


# ----------------------------------------------------------------------------------------------
# The mode
# ----------------------------------------------------------------------------------------------


class _Unchanged:
    """Distinct from `None`, which is a perfectly good thing for a field to already hold."""

    def __repr__(self) -> str:  # pragma: no cover - debugging only
        return "<unchanged>"


_UNCHANGED = _Unchanged()


def _apply(key: Field, current: object, winner: object, mode: RefreshMode) -> object:
    """The matrix, one cell.

    `Local only` is `Default` over a shorter chain, not a fourth behaviour: the remote sources are
    already gone by the time this runs.
    """
    rule = LIST_RULE.get(key)
    if rule is ListRule.REDERIVED:
        # No mode branch at all: the source *is* the truth for this field, so the only question is
        # whether it says something different from what the row holds. An unchanged directory
        # produces an equal list and nothing is written, which is what keeps "a rescan of an
        # unchanged library changes nothing" true (006 AC-2's first half).
        return winner if winner != current else _UNCHANGED
    if rule is ListRule.UNION:
        return _union(current, winner, mode)
    if rule is ListRule.ENRICH:
        return _enrich(current, winner, mode)
    if rule is ListRule.ACCUMULATE:
        return _accumulate(current, winner, mode)

    if is_value(current) and mode is not RefreshMode.REPLACE:
        return _UNCHANGED
    return winner if winner != current else _UNCHANGED


def _union(current: object, winner: object, mode: RefreshMode) -> object:
    """`Studios` and `Tags`: what the item has, then what the source adds, distinct ignoring case.

    The item's own order comes first and its own spelling survives - a studio already recorded as
    `Fixture Pictures` is not rewritten to `FIXTURE PICTURES` by a source that shouts.
    """
    if mode is RefreshMode.REPLACE or not is_value(current):
        return winner
    existing = list(_strings(current))
    seen = {value.casefold() for value in existing}
    added = [value for value in _strings(winner) if value.casefold() not in seen]
    return existing + added if added else _UNCHANGED


def _enrich(current: object, winner: object, mode: RefreshMode) -> object:
    """`People`: **nobody is added and nobody is removed**; existing entries are filled in.

    Matched by name with diacritics stripped, case-insensitively, which is the reference's own
    matching `[source: MediaBrowser.Providers/Manager/MetadataService.cs MergePeople @ v10.11.11]`.
    A role or a billing position the item is missing is taken from the source; one it already has
    is kept. So a sidecar that names a cast without roles, refreshed against a provider that has
    them, gains the roles without the cast list changing.
    """
    if mode is RefreshMode.REPLACE or not is_value(current):
        return winner
    existing = _people(current)
    offered = _people(winner)
    if not existing or not offered:
        return _UNCHANGED

    by_name: dict[str, list[PersonCredit]] = {}
    for person in offered:
        by_name.setdefault(_fold_person(person.name), []).append(person)

    enriched: list[PersonCredit] = []
    changed = False
    for index, person in enumerate(existing):
        matches = by_name.get(_fold_person(person.name), [])
        if not matches:
            enriched.append(person)
            continue
        source = matches[index] if index < len(matches) else matches[0]
        filled = PersonCredit(
            name=person.name,
            kind=person.kind,
            role=person.role or source.role,
            sort_order=person.sort_order if person.sort_order is not None else source.sort_order,
        )
        changed = changed or filled != person
        enriched.append(filled)
    return enriched if changed else _UNCHANGED


def _accumulate(current: object, winner: object, mode: RefreshMode) -> object:
    """`ProviderIds`: key by key, and **an id the item already has is not replaced** unless the
    mode is `Replace`.

    That asymmetry is the reference's and it is the right one: an id is the user's decision about
    what this thing is (spec section 3.2), and a default refresh that overwrote one would undo a
    correction without being asked to.
    """
    existing = dict(_ids(current))
    incoming = dict(_ids(winner))
    if not incoming:
        return _UNCHANGED
    merged = dict(existing)
    for name, value in incoming.items():
        if mode is RefreshMode.REPLACE or name not in merged:
            merged[name] = value
    return merged if merged != existing else _UNCHANGED


# ----------------------------------------------------------------------------------------------
# Shapes
# ----------------------------------------------------------------------------------------------


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Sequence):
        return [str(one) for one in value]
    return []


def _people(value: object) -> list[PersonCredit]:
    if isinstance(value, Sequence) and not isinstance(value, str):
        return [one for one in value if isinstance(one, PersonCredit)]
    return []


def _ids(value: object) -> Mapping[str, str]:
    if isinstance(value, Mapping):
        return {str(name): str(one) for name, one in value.items()}
    return {}


def _fold_person(name: str) -> str:
    """Case-folded and stripped of combining marks, which is how the reference matches a person
    against a person `[source: MediaBrowser.Providers/Manager/MetadataService.cs @ v10.11.11]`.

    Note that this is **not** the by-name fold of `library/identity.py`, which keeps diacritics
    apart on purpose. Two different questions: that one asks whether two spellings are one *item*,
    this one asks whether two credits are one *person in one cast list*.
    """
    decomposed = unicodedata.normalize("NFD", name)
    return (
        "".join(character for character in decomposed if not unicodedata.combining(character))
        .casefold()
        .strip()
    )


__all__ = [
    "CHAIN_OF",
    "LIST_RULE",
    "Current",
    "ListRule",
    "MetadataChanges",
    "Source",
    "SourceKind",
    "merge",
]
