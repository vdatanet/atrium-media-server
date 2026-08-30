# SPDX-License-Identifier: GPL-3.0-or-later
"""Which files a scan looks at, and why it walked past the rest.

A library root holds artwork, subtitles, sidecars, trickplay indexes, operating-system detritus and
somebody's downloads in progress. **None of that is an error** (003 spec section 3.2): a scanner
that complained about a `.DS_Store` would complain on every real library, and one that treated a
half-copied file as a short film would produce an item that breaks the moment it is played.

So this module produces two lists rather than one. Everything it walked past comes back **with the
reason**, because 003 plan section 7 needs an unreadable file to be counted and reported rather
than silently dropped, and because "the scan found fewer items than I expected" is a question
somebody will ask.

**Nothing here decides what a file *is*** - that is the resolver. This decides only whether the
resolver gets to see it.

**Files being written are detected by looking twice.** A download in progress has a size that
changes, so the walk records a size for every candidate and then reads it again: anything that
moved is skipped *this* scan and picked up by the next one. The two passes are separate functions
so a test can change a file between them without the suite sleeping.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path, PurePosixPath

from atrium.domain.items import CollectionType
from atrium.library.naming.external import SUBTITLE_EXTENSIONS

#: Extensions that become items, per collection type.
#:
#: The first three of each were **measured** on a library of 8,288 items
#: `[probe: tools/probe_library_extensions.py, Jellyfin 10.11.11, 2026-08-27]`, and the rest are
#: 003 spec section 3.2's conservative union: that measurement is a lower bound, so an extension
#: nobody had a file of is unmeasured rather than refused.
#:
#: **The lists do not fall back to one another, and that is measured, not assumed.** Under the
#: reference's `movies` and `tvshows` roots, 89 `.mp3` files and 3 `.mka` files produced no item of
#: any type - so `.mp3` appears below under `music` and nowhere else. A scanner generous enough to
#: admit every audio extension everywhere would turn theme music and commentary tracks into items
#: the reference does not have. docs/compatibility/behaviours.md section 2.15.
VIDEO_EXTENSIONS = frozenset(
    {
        ".mkv",
        ".mp4",
        ".avi",
        ".ts",  # measured
        ".m4v",
        ".mov",
        ".wmv",
        ".flv",
        ".webm",
        ".mpg",
        ".mpeg",
        ".m2ts",
        ".mts",
        ".vob",
        ".ogv",
        ".divx",
        ".3gp",
        ".rmvb",
        ".asf",
    }
)
AUDIO_EXTENSIONS = frozenset(
    {
        ".flac",
        ".m4a",
        ".dsf",  # measured
        ".mp3",
        ".ogg",
        ".oga",
        ".opus",
        ".wav",
        ".aac",
        ".wma",
        ".aiff",
        ".aif",
        ".ape",
        ".dff",
        ".mka",
        ".alac",
        ".wv",
        ".mpc",
    }
)

EXTENSIONS: dict[CollectionType, frozenset[str]] = {
    CollectionType.MOVIES: VIDEO_EXTENSIONS,
    CollectionType.TVSHOWS: VIDEO_EXTENSIONS,
    CollectionType.MUSIC: AUDIO_EXTENSIONS,
}

#: A file whose stem ends in one of these is an extra rather than the work (003 spec section 3.4).
#:
#: Written from the conventions these follow, not transcribed from the reference's table
#: (Principle IV). The corpus at T9 is what decides whether the list is right.
EXTRA_SUFFIXES = (
    "-trailer",
    "-sample",
    "-featurette",
    "-featurettes",
    "-short",
    "-shorts",
    "-scene",
    "-scenes",
    "-clip",
    "-clips",
    "-interview",
    "-interviews",
    "-behindthescenes",
    "-deleted",
    "-deletedscene",
    "-deletedscenes",
    "-extra",
    "-extras",
    "-other",
    "-theme",
)

#: A directory whose name is one of these holds extras, whatever the files inside are called.
#:
#: **`specials` is deliberately absent.** It is an alias for season zero (003 spec section 3.4),
#: not an extras folder, and treating it as one would silently delete every special episode in
#: every series - which looks like a correct scan right up until somebody goes looking for one.
EXTRA_DIRECTORIES = frozenset(
    {
        "extras",
        "extra",
        "trailers",
        "featurettes",
        "behind the scenes",
        "behindthescenes",
        "deleted scenes",
        "deletedscenes",
        "interviews",
        "scenes",
        "shorts",
        "other",
        "sample",
        "samples",
    }
)

#: A directory holding this file is excluded, and so is everything under it.
IGNORE_MARKER = ".ignore"


class Skip(StrEnum):
    """Why a file was walked past. Every one of these is reported, none is an error."""

    HIDDEN = "a path component begins with a dot"
    IGNORED = f"a {IGNORE_MARKER} file marks this directory excluded"
    EXTRA = "a trailer, sample or other extra rather than the work"
    EXTENSION = "not a media extension for this collection type"
    EMPTY = "zero bytes, so an incomplete copy rather than a file"
    BEING_WRITTEN = "its size changed between two passes, so it is still being written"
    UNREADABLE = "could not be read"


@dataclass(frozen=True, slots=True)
class Candidate:
    """A file the resolver will be asked about."""

    relative_path: str
    size: int
    mtime_ns: int


@dataclass(frozen=True, slots=True)
class Skipped:
    relative_path: str
    reason: Skip


@dataclass(frozen=True, slots=True)
class WalkResult:
    candidates: tuple[Candidate, ...] = ()
    skipped: tuple[Skipped, ...] = field(default_factory=tuple)

    subtitles: tuple[Candidate, ...] = field(default_factory=tuple)
    """Files carrying one of the nine extensions the reference admits as an external subtitle
    `[source: Emby.Naming/Common/NamingOptions.cs:163-174 @ v10.11.11]`, statted like a candidate.

    **They are in `skipped` as well, and that is deliberate.** A subtitle produces no item, the
    scan report counts files that produced none, and moving these out of that count would change
    an operator-facing number to record something the operator did not ask about. This is the same
    set seen a second way, not a set taken out of the first.

    Which media file each belongs to is not decided here - it is a question about two names and
    `library/naming/external.py` answers it (011 plan section 6.2).
    """

    def reasons(self) -> dict[Skip, int]:
        """How many files each reason accounted for, which is what a scan summary reports."""
        counts: dict[Skip, int] = {}
        for one in self.skipped:
            counts[one.reason] = counts.get(one.reason, 0) + 1
        return counts


def walk(root: Path, collection_type: CollectionType) -> WalkResult:
    """Both passes: find the candidates, then drop the ones that moved while we looked."""
    return settle(root, found(root, collection_type))


def found(root: Path, collection_type: CollectionType) -> WalkResult:
    """The first pass: traverse, filter, and stat what survives.

    Directories are pruned as they are met rather than filtered afterwards, so an excluded tree
    costs one `readdir` rather than a full descent into somebody's photo archive.
    """
    extensions = EXTENSIONS[collection_type]
    candidates: list[Candidate] = []
    skipped: list[Skipped] = []
    subtitles: list[Candidate] = []

    def unreadable(error: OSError) -> None:
        # `os.walk` discards directory errors unless given this, and the default is the dangerous
        # one here: a directory the scan cannot list would simply not appear, with nothing said.
        # Every file under it would then look deleted to the diff at T18 - a partial loss too
        # small for the emptiness guard to catch and large enough for a user to notice.
        where = Path(str(error.filename or root))
        skipped.append(Skipped(_relative(_safe_relative(where, root)), Skip.UNREADABLE))

    for directory, subdirectories, filenames in os.walk(
        root, onerror=unreadable, followlinks=False
    ):
        here = Path(directory)
        relative_directory = here.relative_to(root)

        if IGNORE_MARKER in filenames:
            # The operator's explicit exclusion. Nothing below it is even listed.
            subdirectories[:] = []
            skipped.append(Skipped(_relative(relative_directory), Skip.IGNORED))
            continue

        subdirectories[:] = [name for name in sorted(subdirectories) if not name.startswith(".")]

        for filename in sorted(filenames):
            relative = _relative(relative_directory / filename)
            reason = _refuse(filename, relative_directory, extensions)
            if reason is not None:
                skipped.append(Skipped(relative, reason))
                # A subtitle file is refused for its extension and then looked at again, because
                # it is not a candidate and is not nothing either. Only that refusal: a hidden or
                # excluded file stays walked past, which is 003's rule and not this feature's to
                # loosen.
                if reason is Skip.EXTENSION and _is_subtitle(filename):
                    stat = _stat_or_none(here / filename)
                    if stat is not None and stat.st_size > 0:
                        subtitles.append(
                            Candidate(
                                relative_path=relative,
                                size=stat.st_size,
                                mtime_ns=stat.st_mtime_ns,
                            )
                        )
                continue
            try:
                stat = (here / filename).stat()
            except OSError:
                skipped.append(Skipped(relative, Skip.UNREADABLE))
                continue
            if stat.st_size == 0:
                skipped.append(Skipped(relative, Skip.EMPTY))
                continue
            candidates.append(
                Candidate(relative_path=relative, size=stat.st_size, mtime_ns=stat.st_mtime_ns)
            )

    return WalkResult(
        candidates=tuple(candidates), skipped=tuple(skipped), subtitles=tuple(subtitles)
    )


def settle(root: Path, first: WalkResult) -> WalkResult:
    """The second pass: anything whose size moved since the first pass is still being written.

    Separate from `found` on purpose. A file being copied has a size that changes, and the gap
    between the two passes is the traversal itself - so this needs no sleep, and a test can change
    a file between the two calls without one either.

    A candidate that has since vanished is `UNREADABLE` rather than an error: a file can be moved
    away mid-scan and that is not a failure of the scan.
    """
    candidates: list[Candidate] = []
    skipped = list(first.skipped)

    for candidate in first.candidates:
        try:
            stat = (root / candidate.relative_path).stat()
        except OSError:
            skipped.append(Skipped(candidate.relative_path, Skip.UNREADABLE))
            continue
        if stat.st_size != candidate.size:
            skipped.append(Skipped(candidate.relative_path, Skip.BEING_WRITTEN))
            continue
        candidates.append(
            Candidate(
                relative_path=candidate.relative_path,
                size=stat.st_size,
                mtime_ns=stat.st_mtime_ns,
            )
        )

    # Subtitles settle too, and silently: a half-copied `.srt` inspected mid-write would store a
    # cue list nobody wrote. What it does **not** get is a second `Skipped` entry - it already has
    # one, for its extension, and counting it twice would move the operator's number.
    subtitles: list[Candidate] = []
    for subtitle in first.subtitles:
        settled = _stat_or_none(root / subtitle.relative_path)
        if settled is None or settled.st_size != subtitle.size:
            continue
        subtitles.append(
            Candidate(
                relative_path=subtitle.relative_path,
                size=settled.st_size,
                mtime_ns=settled.st_mtime_ns,
            )
        )

    return WalkResult(
        candidates=tuple(candidates), skipped=tuple(skipped), subtitles=tuple(subtitles)
    )


def _is_subtitle(filename: str) -> bool:
    return PurePosixPath(filename).suffix.lower() in SUBTITLE_EXTENSIONS


def _stat_or_none(path: Path) -> os.stat_result | None:
    """`stat`, or nothing. A file that vanished between the listing and the call is not an error
    here: the candidate path already reports one, and a subtitle reports its extension."""
    try:
        return path.stat()
    except OSError:
        return None


def is_extra(relative_path: str) -> bool:
    """Whether this path is an extra: by the file's suffix, or by a directory it sits in."""
    path = PurePosixPath(relative_path)
    if any(part.lower() in EXTRA_DIRECTORIES for part in path.parts[:-1]):
        return True
    return path.stem.lower().endswith(EXTRA_SUFFIXES)


def _refuse(filename: str, relative_directory: Path, extensions: Iterable[str]) -> Skip | None:
    if filename.startswith("."):
        return Skip.HIDDEN
    relative = _relative(relative_directory / filename)
    if PurePosixPath(filename).suffix.lower() not in extensions:
        return Skip.EXTENSION
    if is_extra(relative):
        return Skip.EXTRA
    return None


def _safe_relative(path: Path, root: Path) -> Path:
    """`relative_to` for a path that may not be under the root at all, which an error can be."""
    try:
        return path.relative_to(root)
    except ValueError:
        return path


def _relative(path: Path) -> str:
    """Relative, POSIX-separated, and never `.` for the root itself."""
    text = path.as_posix()
    return "" if text == "." else text


__all__ = [
    "AUDIO_EXTENSIONS",
    "EXTENSIONS",
    "EXTRA_DIRECTORIES",
    "EXTRA_SUFFIXES",
    "IGNORE_MARKER",
    "VIDEO_EXTENSIONS",
    "Candidate",
    "Skip",
    "Skipped",
    "WalkResult",
    "found",
    "is_extra",
    "settle",
    "walk",
]
