# SPDX-License-Identifier: GPL-3.0-or-later
"""What a subtitle track is called: the one localised string this project writes.

011 §3.2, OQ-4 and plan §6.4. An HLS master playlist labels every announced subtitle track with
the stream's display title, and `NAME` is a **required** attribute of `#EXT-X-MEDIA` - so "leave
it absent, as 008 does" is not available here. This module writes it, in the invariant form: the
reference's own assembly, its own English words, and this project's own language table.

## The assembly

Up to six pieces joined by `" - "`, in this order `[source:
MediaBrowser.Model/Entities/MediaStream.cs:390-465 @ v10.11.11]`:

1. the language's **name**, or the undefined marker when the stream states no language;
2. a hearing-impaired word, when the flag is set;
3. a default word, when it is set;
4. a forced word, when it is set;
5. the **codec, upper-cased**;
6. an external word, when the stream came from a file beside the media.

When the stream has a title of its own the title leads instead, and each of the six is appended
only if the title does not already contain it as a case-insensitive substring - so a track called
`Ingles SDH` beside an English language name keeps both, and one called `Forced English` swallows
two attributes at once.

**Reproduced from the wire rather than from the source.** Every one of 909 subtitle streams of a
real library rebuilds exactly from its own properties under the rule above - the order, the
separator, the codec's casing and the substring suppression all measured rather than read
`[probe: tools/probe_stream_display_title.py, Jellyfin 10.11.11, 2026-08-30]`.

## The five localised words, and the one that is not the literal it looks like

Four flag words and a marker for a stream with no language. Plan §6.4 took all five from the
literals the reference compiles into the assembly, on the argument that a server which localises
nothing writes those. **No served stream is ever in that state.** Every subtitle stream carries
all five localised properties on the wire, filled from the server's translation table on the way
out `[source:
Jellyfin.Server.Implementations/Item/MediaStreamRepository.cs:156-167 @ v10.11.11]`, measured on
910 of 910 subtitle streams - so the fallback literals are unreachable and the words that are
actually written are the translation table's, in the server's interface culture. Same probe.

Four of the five are the same string either way. **The marker is not**: the compiled-in fallback is
`Und` and the English translation table's row is `Undefined` `[source:
Emby.Server.Implementations/Localization/Core/en-US.json:84 @ v10.11.11]`, so a server writing
`Und` writes a string no reference of any configuration writes. This module writes `Undefined`,
which is what an English-configured reference writes, and that is the whole of what 011 T10
corrected in plan §6.4.

## The language name is the divergence, and it is the only one

The reference resolves the language tag against the **platform's** culture data in the server's
interface culture: `Español` on a Spanish host, `Spanish` on an English one. This project has one
language table, the generated `metadata/cultures.py`, and its display names are the ISO 639-2
English ones `/Localization/Cultures` serves - `Spanish; Castilian` where a platform table says
`Spanish`. Five of the 29 language tags a real library carries have a display name with an
alternate spelling or a qualifier and therefore cannot equal a platform name in any culture; the
other 24 are a single word. Same probe.

That difference is the divergence 011 §3.2 accepted, on the argument that `NAME` is a label a
person reads in a track picker and the attributes clients branch on - `LANGUAGE`, `FORCED`,
`DEFAULT`, `URI` - are byte-identical. It stays recorded in behaviours §5's localised-properties
row, whose closing mechanism closes this with it.

**The table is an argument, not an import.** The caller passes the index `library/naming/external`
already builds for filenames - token to culture row, first row winning - so this module ships no
second table (004 T15 is the record of what a second table costs), the matrix below is a table
test, and `media/` gains no dependency on `library/`.

**Only the subtitle assembly is here.** The reference builds an audio title and a video title by
different rules in the same property, and this project needs neither: `MediaStream.DisplayTitle`
stays absent from every response (008 §3.1), because a JSON property can be absent and a manifest
attribute cannot.
"""

from __future__ import annotations

from collections.abc import Mapping

from atrium.domain.media import InspectedStream
from atrium.metadata.cultures import Culture

#: What the pieces are joined by, and what introduces each piece appended to a stream's own title
#: `[source: MediaBrowser.Model/Entities/MediaStream.cs:458, 465 @ v10.11.11]`. The audio branch
#: joins the same kind of list on a single space; this one does not.
JOIN = " - "

#: The word for a stream that states no language. **The translation table's row, not the literal
#: compiled into the assembly**: `Und` is unreachable on a served stream (see the module
#: docstring) `[source: Emby.Server.Implementations/Localization/Core/en-US.json:84 @ v10.11.11]`.
UNDEFINED = "Undefined"

#: The four flag words, English, identical in the translation table and in the assembly's own
#: fallbacks `[source: Emby.Server.Implementations/Localization/Core/en-US.json:12, 15, 19, 31 @
#: v10.11.11]`.
HEARING_IMPAIRED = "Hearing Impaired"
DEFAULT = "Default"
FORCED = "Forced"
EXTERNAL = "External"


def first_to_upper(text: str) -> str:
    """The first character upper-cased, and only when it is a lower-case one.

    The reference applies this to the language name and to the raw tag it falls back to `[source:
    MediaBrowser.Model/Entities/MediaStream.cs:418,
    MediaBrowser.Model/Extensions/StringHelper.cs:13-35 @ v10.11.11]`. It is not `str.capitalize`,
    which would lower-case the rest and turn `zh-HK` into `Zh-hk`, and it is not a bare
    `text[:1].upper()` either: a character whose upper case is more than one character - `ß` -
    is left alone, because the reference upper-cases a `char` and a `char` cannot grow.
    """
    if not text or not text[0].islower():
        return text
    first = text[0].upper()
    return text if len(first) != 1 else first + text[1:]


def language_name(tag: str, languages: Mapping[str, Culture]) -> str:
    """What to call the language a stream states, given the culture index.

    The row's display name when the tag names a row, and the tag itself when it names none -
    which is the reference's own fallback, and it upper-cases the first letter of either.
    """
    culture = languages.get(tag.lower())
    return first_to_upper(culture.display_name if culture is not None else tag)


def display_title(stream: InspectedStream, languages: Mapping[str, Culture]) -> str:
    """The label a manifest gives one subtitle track, in the invariant form.

    Pure, and total: every subtitle stream has a title, because the marker stands in for a
    missing language and the remaining five pieces are each optional.
    """
    attributes = [
        language_name(stream.language, languages) if stream.language else UNDEFINED,
    ]
    if stream.is_hearing_impaired:
        attributes.append(HEARING_IMPAIRED)
    if stream.is_default:
        attributes.append(DEFAULT)
    if stream.is_forced:
        attributes.append(FORCED)
    if stream.codec:
        attributes.append(stream.codec.upper())
    if stream.is_external:
        attributes.append(EXTERNAL)

    title = stream.title or ""
    if not title:
        return JOIN.join(attributes)
    folded = title.lower()
    return title + "".join(
        JOIN + attribute for attribute in attributes if attribute.lower() not in folded
    )


__all__ = [
    "DEFAULT",
    "EXTERNAL",
    "FORCED",
    "HEARING_IMPAIRED",
    "JOIN",
    "UNDEFINED",
    "display_title",
    "first_to_upper",
    "language_name",
]
