# SPDX-License-Identifier: GPL-3.0-or-later
"""What a filename beside a media file says, one row at a time.

011 spec section 3.6 and AC-11. The rule is a stem match and a right-to-left read, and the reason
it is a table rather than a paragraph is that **three of its clauses invert on a neighbouring
input**: a vocabulary matched by containment beside one matched by equality, a two-letter code
that is a language on one filename and a flag on the next, and a language written as a name rather
than as a code on nine of the 192 culture rows.

Every expectation here is derived from the reference's own behaviour `[source:
Emby.Naming/ExternalFiles/ExternalPathParser.cs, MediaBrowser.Providers/MediaInfo/
MediaInfoResolver.cs:234-250 @ v10.11.11]` and the reproduction was checked against a real library
`[probe: tools/probe_sidecar_subtitles.py, Jellyfin 10.11.11, 2026-08-29]` - except the `hin`
branch, which that library has no filename to reach (011 plan section 6.8) and which is therefore
read here and reported as unreached there.
"""

from __future__ import annotations

import pytest

from atrium.library.naming import SUBTITLE_EXTENSIONS, ExternalName, parse_external
from atrium.library.naming.external import claimed_suffix
from atrium.metadata.cultures import CULTURES

STEM = "film"


def parsed(filename: str, media_stem: str = STEM) -> ExternalName:
    """The claimed answer, refusing to let a row pass by not being claimed at all."""
    answer = parse_external(filename, media_stem)
    assert answer is not None, f"{filename!r} was not claimed by {media_stem!r}"
    return answer


# ------------------------------------------------------------------------------------------
# The stem match: which files are claimed at all
# ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("extension", SUBTITLE_EXTENSIONS)
def test_every_admitted_extension_is_claimed(extension: str) -> None:
    """Nine of them, two naming image formats. A tenth would be a stream nothing can serve."""
    assert parse_external(f"{STEM}{extension}", STEM) is not None


@pytest.mark.parametrize("filename", ["film.txt", "film.eng.txt", "film.nfo", "film.mkv", "film"])
def test_an_extension_outside_the_nine_claims_nothing(filename: str) -> None:
    assert parse_external(filename, STEM) is None


def test_the_stem_must_stop_or_continue_with_a_delimiter() -> None:
    """**The row that keeps one film's subtitle off another film**, and the one a `startswith`
    would fail: `film` is a prefix of `film 2` and of `film2`, and neither of their sidecars
    belongs to it."""
    assert parse_external("film 2.eng.srt", STEM) is None
    assert parse_external("film2.srt", STEM) is None
    assert parse_external("film-2.eng.srt", STEM) is None
    assert parse_external("film 2.eng.srt", "film 2") is not None


def test_a_shorter_name_than_the_stem_claims_nothing() -> None:
    assert parse_external("fil.srt", STEM) is None


def test_the_match_ignores_case_on_both_halves() -> None:
    answer = parsed("FILM.ENG.SRT")
    assert answer.language == "eng", "a shouting filename is the same filename"


def test_a_media_stem_with_dots_of_its_own_still_matches() -> None:
    """`Path.GetFileNameWithoutExtension` strips one extension, so a release-named film brings its
    own dots into the prefix and the right-to-left read starts after all of them."""
    answer = parsed("A.Film.2019.1080p.eng.forced.srt", "A.Film.2019.1080p")
    assert (answer.language, answer.is_forced, answer.title) == ("eng", True, None)


def test_the_claimed_suffix_of_a_bare_stem_is_empty_and_not_a_miss() -> None:
    """The two answers a caller must not conflate: `None` is "not this film's file", `""` is
    "this film's file, saying nothing about itself"."""
    assert claimed_suffix("film.srt", STEM) == ""
    assert claimed_suffix("film.eng.srt", STEM) == ".eng"
    assert claimed_suffix("film2.srt", STEM) is None


# ------------------------------------------------------------------------------------------
# The right-to-left read: language, three flags, and whatever is left
# ------------------------------------------------------------------------------------------

#: filename → (language, default, forced, hearing-impaired, title)
MATRIX: tuple[tuple[str, str | None, bool, bool, bool, str | None], ...] = (
    # A bare stem says nothing at all - no flags, no language, and a title of None rather than "".
    ("film.srt", None, False, False, False, None),
    # One language token, in each of the four spellings the culture lookup admits.
    ("film.eng.srt", "eng", False, False, False, None),
    ("film.en.srt", "eng", False, False, False, None),
    ("film.English.srt", "eng", False, False, False, None),
    ("film.fre.srt", "fra", False, False, False, None),
    # Each flag vocabulary, alone.
    ("film.default.srt", None, True, False, False, None),
    ("film.foreign.srt", None, False, True, False, None),
    ("film.forced.srt", None, False, True, False, None),
    ("film.cc.srt", None, False, False, True, None),
    ("film.sdh.srt", None, False, False, True, None),
    # Containment against equality. `forcedspanish` is forced and never reaches the language
    # lookup; `hix` is not hearing-impaired and becomes a title instead.
    ("film.forcedspanish.srt", None, False, True, False, None),
    ("film.hix.srt", None, False, False, False, "hix"),
    # `hi` is Hindi first and a flag second.
    ("film.hi.srt", "hin", False, False, False, None),
    # The branch behind it: a second language token *behind* Hindi takes the language and sets
    # the flag, because the `hi` in front of it was never the flag it looked like.
    ("film.spa.hi.srt", "spa", False, False, True, None),
    ("film.eng.hi.srt", "eng", False, False, True, None),
    # And the guard on that branch: a second language token behind anything *else* is a title.
    ("film.spa.eng.srt", "eng", False, False, False, "spa"),
    # Nine culture rows are written as a name rather than as a code, and two of them are not
    # regional tags at all.
    ("film.ell.srt", "Greek, Modern (1453-)", False, False, False, None),
    ("film.gre.srt", "Greek, Modern (1453-)", False, False, False, None),
    ("film.el.srt", "Greek, Modern (1453-)", False, False, False, None),
    ("film.lub.srt", "Luba-Katanga", False, False, False, None),
    ("film.lu.srt", "Luba-Katanga", False, False, False, None),
    ("film.pt-br.srt", "pt-br", False, False, False, None),
    # Everything nothing claimed becomes the title, in filename order.
    ("film.Director's Cut.eng.srt", "eng", False, False, False, "Director's Cut"),
    ("film.a.b.srt", None, False, False, False, "a.b"),
    ("film.Signs and Songs.srt", None, False, False, False, "Signs and Songs"),
    # Everything at once, read from the right.
    ("film.Commentary.eng.forced.default.srt", "eng", True, True, False, "Commentary"),
    # An empty token is claimed by nothing, so the title is the empty string rather than None.
    # Faithful rather than desirable: the distinction is the reference's own.
    ("film..srt", None, False, False, False, ""),
)


@pytest.mark.parametrize(
    ("filename", "language", "is_default", "is_forced", "is_hearing_impaired", "title"),
    MATRIX,
    ids=[row[0] for row in MATRIX],
)
def test_the_filename_matrix(
    filename: str,
    language: str | None,
    is_default: bool,
    is_forced: bool,
    is_hearing_impaired: bool,
    title: str | None,
) -> None:
    answer = parsed(filename)
    assert answer == ExternalName(
        filename=filename,
        language=language,
        title=title,
        is_default=is_default,
        is_forced=is_forced,
        is_hearing_impaired=is_hearing_impaired,
    )


def test_the_matrix_reaches_every_flag_in_every_vocabulary() -> None:
    """A matrix that stopped exercising a vocabulary would go on passing. This is the check that
    the three above are each reached, and that the language half is reached with them."""
    reached = [parsed(name) for name, *_ in MATRIX]
    assert any(one.is_default for one in reached)
    assert any(one.is_forced for one in reached)
    assert any(one.is_hearing_impaired for one in reached)
    assert any(one.language for one in reached)
    assert any(one.title for one in reached)


# ------------------------------------------------------------------------------------------
# The language table, and the dash
# ------------------------------------------------------------------------------------------


def test_nine_culture_rows_are_written_as_a_name_and_two_are_not_regional() -> None:
    """The tasks gate's correction to plan section 6.2, asserted against the table itself.

    "The eight regional rows, `zh-hk` and its siblings" describes a table this project does not
    have: there are nine, and `Greek, Modern (1453-)` and `Luba-Katanga` carry their dash for
    reasons that have nothing to do with a region.
    """
    dashed = [culture.name for culture in CULTURES if "-" in culture.name]
    assert len(dashed) == 9, dashed
    assert "Greek, Modern (1453-)" in dashed
    assert "Luba-Katanga" in dashed


def test_the_first_row_that_claims_a_token_wins_it() -> None:
    """**Five** culture rows carry `zho` and two carry `spa`, so the token alone does not name a
    row - the table's order does, and the reference takes the first row it walks past.

    The discriminating half is that four of the five `zho` rows would be written as a *name*:
    a map built last-wins would answer `zh-tw` here, which is a language a sidecar never claimed.
    """
    zho = [culture.name for culture in CULTURES if "zho" in culture.three_letters]
    assert len(zho) == 5 and zho[0] == "Chinese", zho
    assert parsed("film.zho.srt").language == "zho"
    assert parsed("film.spa.srt").language == "spa", "es-419 is the second row that carries it"


def test_a_token_no_culture_claims_is_not_a_language() -> None:
    for token in ("cc", "sdh", "forced", "default", "hix", "Commentary"):
        assert parse_external(f"film.{token}.srt", STEM) is not None
        assert parsed(f"film.{token}.srt").language is None, token
