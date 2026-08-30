# SPDX-License-Identifier: GPL-3.0-or-later
"""What a subtitle track is called, one piece at a time.

011 spec section 3.2 (the `NAME` box), OQ-4 and plan section 6.4. The string is six optional
pieces in a fixed order, and the reason it is a table rather than a paragraph is that the pieces
interact: a stream's own title suppresses any attribute it already contains, so the assembly is
not a `join` and a test of the joined form alone would pass with the suppression deleted.

Every expectation is derived from the reference's own behaviour `[source:
MediaBrowser.Model/Entities/MediaStream.cs:390-465 @ v10.11.11]` and the assembly was reproduced
against a real library, 909 of 909 subtitle streams rebuilt exactly from their own properties
`[probe: tools/probe_stream_display_title.py, Jellyfin 10.11.11, 2026-08-30]` - which is also
where the two costs pinned at the bottom were measured.
"""

from __future__ import annotations

import pytest

from atrium.domain.media import InspectedStream, StreamKind
from atrium.library.naming.external import LANGUAGE_TOKENS
from atrium.media.names import (
    DEFAULT,
    EXTERNAL,
    FORCED,
    HEARING_IMPAIRED,
    UNDEFINED,
    display_title,
    first_to_upper,
)
from atrium.metadata.cultures import CULTURES, Culture


def a_subtitle_stream(**overrides: object) -> InspectedStream:
    values: dict[str, object] = {
        "index": 2,
        "kind": StreamKind.SUBTITLE,
        "codec": "subrip",
        "language": "eng",
    }
    values.update(overrides)
    return InspectedStream(**values)  # type: ignore[arg-type]


def named(**overrides: object) -> str:
    return display_title(a_subtitle_stream(**overrides), LANGUAGE_TOKENS)


# ------------------------------------------------------------------------------------------
# The six pieces, and the order they arrive in
# ------------------------------------------------------------------------------------------


def test_every_piece_at_once_in_the_reference_order() -> None:
    """The whole assembly, which is the row that pins the order and the separator together.

    An assembly that emitted the same six pieces in any other order would pass every single-piece
    row below and still label every track differently from the reference.
    """
    assert named(
        language="spa",
        is_hearing_impaired=True,
        is_default=True,
        is_forced=True,
        codec="subrip",
        is_external=True,
    ) == ("Spanish; Castilian - Hearing Impaired - Default - Forced - SUBRIP - External")


def test_a_bare_track_is_its_language_and_its_codec() -> None:
    assert named() == "English - SUBRIP"


@pytest.mark.parametrize(
    ("flag", "word"),
    [
        ("is_hearing_impaired", HEARING_IMPAIRED),
        ("is_default", DEFAULT),
        ("is_forced", FORCED),
        ("is_external", EXTERNAL),
    ],
)
def test_each_flag_word_appears_only_when_its_flag_is_set(flag: str, word: str) -> None:
    assert word not in named()
    assert word in named(**{flag: True})


def test_the_codec_is_upper_cased_and_absent_when_the_stream_states_none() -> None:
    assert named(codec="ass") == "English - ASS"
    assert named(codec=None) == "English"


def test_a_stream_with_no_language_takes_the_undefined_marker() -> None:
    """One of the two costs plan section 6.4 states, and the piece T10 corrected in it: the marker
    is the translation table's `Undefined` and not the `Und` compiled into the assembly, which no
    served stream ever reaches because every one of them carries the localised property filled
    `[source: Jellyfin.Server.Implementations/Item/MediaStreamRepository.cs:156-167 @ v10.11.11]`.
    """
    assert named(language=None) == "Undefined - SUBRIP"
    assert named(language="") == "Undefined - SUBRIP"
    assert UNDEFINED == "Undefined"


def test_the_marker_is_not_the_literal_the_assembly_falls_back_to() -> None:
    """Written as its own row because deleting it is the mistake: `Und` is what the source reads
    like at a glance, it is a plausible string, and it is one no reference of any configuration
    writes `[probe: tools/probe_stream_display_title.py, Jellyfin 10.11.11, 2026-08-30]`."""
    assert UNDEFINED != "Und"


# ------------------------------------------------------------------------------------------
# The title, which is not a seventh piece but a different assembly
# ------------------------------------------------------------------------------------------


def test_a_title_leads_and_the_pieces_follow_it() -> None:
    assert named(title="Signs & Songs") == "Signs & Songs - English - SUBRIP"


def test_a_title_suppresses_an_attribute_it_already_contains() -> None:
    """The rule that makes this an assembly rather than a join. Case-insensitive, and by
    **substring**: `Ingles SDH` does not contain `English`, but `Full English` does."""
    assert named(title="Full English") == "Full English - SUBRIP"
    assert named(title="Ingles SDH") == "Ingles SDH - English - SUBRIP"


def test_the_suppression_ignores_case_in_both_directions() -> None:
    assert named(title="full english subrip") == "full english subrip"
    assert named(title="FULL ENGLISH SUBRIP") == "FULL ENGLISH SUBRIP"


def test_a_title_can_swallow_several_attributes_and_keep_the_rest() -> None:
    assert (
        named(title="Forced english", is_forced=True, is_default=True)
        == "Forced english - Default - SUBRIP"
    )


def test_an_empty_title_is_no_title() -> None:
    """`InspectedStream.title` has three values and one of them is `""` - 011 T3's finding about
    `film..srt`, whose one token is empty and which nothing claims. It must not lead."""
    assert named(title="") == "English - SUBRIP"


# ------------------------------------------------------------------------------------------
# The language name: the table is an argument, and the lookup is the one T3 already built
# ------------------------------------------------------------------------------------------


def test_the_culture_index_is_an_argument_and_decides_the_name() -> None:
    """The whole reason the signature takes the index: a name this project cannot verify against
    a platform table is a **parameter**, so the row below is a test and not a second table."""
    invented = {"spa": Culture("x", "Castilian only", "es", "spa", ("spa",))}
    stream = a_subtitle_stream(language="spa", codec=None)
    assert display_title(stream, invented) == "Castilian only"
    assert display_title(stream, {}) == "Spa", "no row means the tag itself, first letter upper"


def test_a_tag_naming_no_row_falls_back_to_the_tag_itself() -> None:
    assert named(language="qqq") == "Qqq - SUBRIP"


def test_first_row_wins_decides_which_chinese_a_track_is_called() -> None:
    """011 T3's finding, on this side of the table too: five culture rows carry `zho` and the
    first of them is the plain one. A last-wins index would call every Chinese subtitle track
    `Chinese (Traditional)`, on a filename that never mentioned Taiwan."""
    assert named(language="zho") == "Chinese - SUBRIP"


@pytest.mark.parametrize(
    ("tag", "expected"),
    [
        ("eng", "English"),
        ("ENG", "English"),
        ("ell", "Greek, Modern (1453-)"),
        ("pt-br", "Portuguese (Brazil)"),
    ],
)
def test_the_index_answers_the_tags_a_library_carries(tag: str, expected: str) -> None:
    """All 29 language tags a real library carries are a terminological three-letter code, and
    every one of them names a row `[probe: tools/probe_stream_display_title.py, Jellyfin 10.11.11,
    2026-08-30]`."""
    assert named(language=tag, codec=None) == expected


@pytest.mark.parametrize("tag", ["en", "ger", "chi"])
def test_a_tag_shape_the_reference_resolves_for_nothing_still_names_a_row_here(tag: str) -> None:
    """**Wider than the reference, and said out loud rather than left to be discovered.** The
    reference matches a tag with no `-` against the platform's *terminological* three-letter code
    alone, so a two-letter tag and a bibliographic code (`ger`, `chi`) name no culture at all and
    are written as the raw tag with the first letter raised - `En`, `Ger`, `Chi` `[source:
    MediaBrowser.Model/Entities/MediaStream.cs:399-415 @ v10.11.11]`. This project's index is the
    one 011 T3 built and it keys those tokens too, so it answers a name where the reference
    answers the tag. No library measured carries such a tag, so this is read rather than measured
    and the probe reports the shape as unreached on every run; it is inside the `NAME` divergence
    section 3.2 accepts rather than beside it, and plan section 6.4 records it."""
    assert named(language=tag, codec=None) not in {tag, first_to_upper(tag)}


def test_the_language_table_is_the_one_this_project_already_has() -> None:
    """Not a second table (004 T15 is the record of what a second table costs): every name above
    is a row of the generated culture list, reached through the index 011 T3 built for
    filenames."""
    assert LANGUAGE_TOKENS["spa"] in CULTURES
    assert LANGUAGE_TOKENS["spa"].display_name == "Spanish; Castilian"


# ------------------------------------------------------------------------------------------
# `first_to_upper`, which is not `str.capitalize`
# ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("english", "English"),
        ("English", "English"),
        ("ENGLISH", "ENGLISH"),
        ("zh-hk", "Zh-hk"),
        ("", ""),
        ("3d", "3d"),
        ("ßeta", "ßeta"),
    ],
)
def test_only_a_lower_case_first_character_is_raised(text: str, expected: str) -> None:
    """`str.capitalize` would answer `Zh-hk` for `zh-HK` by lower-casing the rest, and `SSeta`
    for `ßeta` by expanding one character into two. The reference upper-cases a single `char` and
    a `char` cannot grow `[source: MediaBrowser.Model/Extensions/StringHelper.cs:13-35 @
    v10.11.11]`."""
    assert first_to_upper(text) == expected


def test_capitalize_would_disagree_on_a_regional_tag() -> None:
    """Pinned so the simplification is refused rather than re-argued."""
    assert first_to_upper("zh-HK") == "Zh-HK" != "zh-HK".capitalize()


# ------------------------------------------------------------------------------------------
# The two costs, stated exactly
# ------------------------------------------------------------------------------------------


def test_the_cost_of_this_projects_own_table_on_a_spanish_track() -> None:
    """Plan section 6.4's own example, pinned: an English-configured reference writes
    `Spanish - Forced - SUBRIP` from its platform culture data, and this project writes the ISO
    639-2 English name its one table has. `LANGUAGE`, `FORCED`, `DEFAULT` and `URI` are
    byte-identical, which is the argument 011 section 3.2 accepts the difference on."""
    assert named(language="spa", is_forced=True) == "Spanish; Castilian - Forced - SUBRIP"


def test_a_track_from_a_file_beside_the_media_says_so_last() -> None:
    """The external word is last, after the codec - the one piece whose position a reader is
    likely to get wrong, because every other flag word comes before it."""
    assert (
        named(language="spa", is_external=True, external_path="film.spa.srt")
        == "Spanish; Castilian - SUBRIP - External"
    )
