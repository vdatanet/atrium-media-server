# SPDX-License-Identifier: GPL-3.0-or-later
"""A file sitting beside a media file, and what its name says about the stream inside it.

**Pure**, like the rest of `naming/`: two strings in, a record out, no filesystem access. The
caller has already walked the directory; this decides which of the files it found belong to one
media file and what each of them claims.

Two rules, and both are the reference's behaviour rather than its expressions (Principle IV):

1. **A stem match.** The candidate's name without its extension has to *begin with* the media
   file's name without its own, case-insensitively, and then either stop there or continue with a
   `.` - so `Film.eng.srt` and `Film.srt` belong to `Film.mkv` and `Film 2.eng.srt` does not
   `[source: MediaBrowser.Providers/MediaInfo/MediaInfoResolver.cs:234-250 @ v10.11.11]`. The
   extension has to be one of nine `[source: Emby.Naming/Common/NamingOptions.cs:163-174 @
   v10.11.11]`, two of which - `.sub` and `.sup` - name image formats.
2. **A right-to-left read of what follows.** One dot-delimited token at a time, from the end,
   each claimed by the first vocabulary that recognises it: a default word, a forced word, a
   language, a hearing-impaired word. Whatever nothing claimed is prepended to the title
   `[source: Emby.Naming/ExternalFiles/ExternalPathParser.cs @ v10.11.11]`.

The reproduction was checked against six items in directories holding up to 259 files each, and
every discovered file, its language, its flags and its title came out identical
`[probe: tools/probe_sidecar_subtitles.py, Jellyfin 10.11.11, 2026-08-29]`.

**Three asymmetries that are not tidiness questions**, each of which a simpler rule gets wrong:

* The default and forced vocabularies match by **containment** and the hearing-impaired one by
  **equality**. `Film.forcedspanish.srt` is forced and `Film.hix.srt` is not hearing-impaired.
* **`hi` is Hindi first and a flag second.** The language lookup runs before the hearing-impaired
  vocabulary, so `Film.hi.srt` is Hindi - a rule that made `hi` a flag outright would mislabel
  every Hindi sidecar in a library. The branch behind it is the one that is easy to miss: when
  the language already claimed is `hin` and a *further* token also resolves to a language, that
  token takes the language **and** sets the hearing-impaired flag, so `Film.spa.hi.srt` is
  Spanish and hearing-impaired.
* **The language written down is not always a three-letter code.** It is the culture row's name
  when that name contains a `-`, and its terminological three-letter code otherwise - so a Greek
  sidecar is `Greek, Modern (1453-)` and a Luba-Katanga one is `Luba-Katanga`, beside the nine
  rows' regional tags like `pt-br`. Nine of the 192 rows carry a dash and two of them are not
  regional tags at all, which is the tasks gate's correction to plan section 6.2.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from atrium.metadata.cultures import CULTURES, Culture

#: The extensions the reference admits as an external subtitle `[source:
#: Emby.Naming/Common/NamingOptions.cs:163-174 @ v10.11.11]`, lower-cased and carrying their dot,
#: which is the form the match is made in.
SUBTITLE_EXTENSIONS: Final[tuple[str, ...]] = (
    ".ass",
    ".mks",
    ".sami",
    ".smi",
    ".srt",
    ".ssa",
    ".sub",
    ".sup",
    ".vtt",
)

#: The one delimiter, and the three flag vocabularies `[source:
#: Emby.Naming/Common/NamingOptions.cs:297-318 @ v10.11.11]`. A tuple rather than a single
#: character because the reference declares a list and reads it as one; the list has one member.
DELIMITERS: Final[tuple[str, ...]] = (".",)
DEFAULT_FLAGS: Final[tuple[str, ...]] = ("default",)
FORCED_FLAGS: Final[tuple[str, ...]] = ("foreign", "forced")
HEARING_IMPAIRED_FLAGS: Final[tuple[str, ...]] = ("cc", "hi", "sdh")

#: The language whose two-letter code collides with a hearing-impaired flag, in the spelling this
#: module writes it in. Named because the collision has a branch of its own below and a reader who
#: meets `"hin"` as a literal there would take it for a typo.
HINDI: Final[str] = "hin"


def _index() -> dict[str, Culture]:
    """Every token that names a language, to the row that claims it, **first row winning**.

    The reference walks its culture list in order and takes the first row whose display name, name,
    three-letter codes or two-letter code matches, case-insensitively `[source:
    Emby.Server.Implementations/Localization/LocalizationManager.cs:172-199 @ v10.11.11]`. Building
    the map row by row and never overwriting an entry answers the same question the same way, and
    answers it without walking 192 rows per token.
    """
    found: dict[str, Culture] = {}
    for culture in CULTURES:
        for token in (
            culture.display_name,
            culture.name,
            *culture.three_letters,
            culture.two_letter,
        ):
            if token:
                found.setdefault(token.lower(), culture)
    return found


#: Built once. `metadata/cultures.py` is generated and immutable, so this is a constant that
#: happens to be computed.
LANGUAGE_TOKENS: Final[dict[str, Culture]] = _index()


def language_of(token: str, *, languages: dict[str, Culture] | None = None) -> str | None:
    """The language a filename token names, spelled the way the reference writes it down.

    The row's `name` when it contains a `-`, its terminological three-letter code otherwise. The
    dash is doing real work: it is what makes a `pt-br` sidecar Brazilian Portuguese rather than
    plain `por`, and - unintentionally, on the reference's part - what makes a Greek one
    `Greek, Modern (1453-)`.
    """
    culture = (LANGUAGE_TOKENS if languages is None else languages).get(token.lower())
    if culture is None:
        return None
    return culture.name if "-" in culture.name else culture.three_letter


@dataclass(frozen=True, slots=True)
class ExternalName:
    """What one filename beside a media file claims about the stream inside it.

    Everything is what the *name* said. The file's own streams are inspected separately and the
    two are merged by the caller, because a name cannot say what codec a `.sub` holds.
    """

    filename: str

    language: str | None = None
    """The reference's spelling (`language_of`), or `None` when no token named a language."""

    title: str | None = None
    """Every token nothing else claimed, in filename order, joined by the delimiter that separated
    them. `None` rather than `""` when everything was claimed, which is the reference's own
    distinction and the one `MergeMetadata` reads."""

    is_default: bool = False
    is_forced: bool = False
    is_hearing_impaired: bool = False


def claimed_suffix(filename: str, media_stem: str) -> str | None:
    """The part of `filename` that follows the media file's stem, or `None` if it claims nothing.

    `""` is a real answer and not a miss: it is what a bare `Film.srt` beside `Film.mkv` yields,
    and it is the case that carries no flags, no language and no title at all.
    """
    stem, dot, extension = filename.rpartition(".")
    if not dot or f".{extension.lower()}" not in SUBTITLE_EXTENSIONS:
        return None
    if len(stem) < len(media_stem) or stem[: len(media_stem)].lower() != media_stem.lower():
        return None
    extra = stem[len(media_stem) :]
    if extra and extra[0] not in DELIMITERS:
        return None
    return extra


def parse_external(
    filename: str, media_stem: str, *, languages: dict[str, Culture] | None = None
) -> ExternalName | None:
    """What the reference would make of one file sitting beside one media file.

    `filename` and `media_stem` are a **name and a stem**, not paths: the caller has the directory
    listing already and `posixpath` is not this module's business. `None` means the file is not
    claimed - a wrong extension, or a stem that does not match - which is a different answer from
    a claimed file that says nothing about itself.

    The `languages` argument exists so the table is an argument in a table test; nothing in the
    server passes it.
    """
    extra = claimed_suffix(filename, media_stem)
    if extra is None:
        return None
    if not extra:
        return ExternalName(filename=filename)

    language: str | None = None
    title = ""
    is_default = is_forced = is_hearing_impaired = False

    remaining = extra
    while remaining:
        cut = max(remaining.rfind(delimiter) for delimiter in DELIMITERS)
        if cut == -1:
            break
        slice_ = remaining[cut:]
        token = slice_[1:].lower()
        named = language_of(token, languages=languages)

        if any(flag in token for flag in DEFAULT_FLAGS):
            is_default = True
        elif any(flag in token for flag in FORCED_FLAGS):
            is_forced = True
        elif named is not None and language is None:
            language = named
        elif named is not None and language == HINDI:
            # The collision, resolved the reference's way: the second language wins the language
            # *and* the flag, because the `hi` behind it was never the flag it looked like.
            is_hearing_impaired = True
            language = named
        elif token in HEARING_IMPAIRED_FLAGS:
            is_hearing_impaired = True
        else:
            title = slice_ + title
        remaining = remaining[:cut]

    return ExternalName(
        filename=filename,
        language=language,
        title=title[1:] if title else None,
        is_default=is_default,
        is_forced=is_forced,
        is_hearing_impaired=is_hearing_impaired,
    )


__all__ = [
    "DEFAULT_FLAGS",
    "DELIMITERS",
    "FORCED_FLAGS",
    "HEARING_IMPAIRED_FLAGS",
    "HINDI",
    "LANGUAGE_TOKENS",
    "SUBTITLE_EXTENSIONS",
    "ExternalName",
    "claimed_suffix",
    "language_of",
    "parse_external",
]
