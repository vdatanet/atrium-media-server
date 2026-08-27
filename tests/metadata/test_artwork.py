# SPDX-License-Identifier: GPL-3.0-or-later
"""Which file is which image, over the fixtures T2 checked in.

**Every name gets a distinct size**, so a test says which file won a type by its dimensions rather
than by its path - which is the thing under test. The sizes are in
`tests/fixtures/metadata/README.md`; `poster` is 2x3, `folder` 4x6, and so on.

T2 built those directories from spec section 3.4's table. T8 then read the reference's own tables
and found the spec's to be a subset with two orderings reversed, so some of what follows asserts
the *measured* behaviour against fixtures designed for the written one - which is why `thumb`
never wins in a fixture directory and gets a temporary file of its own.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from atrium.domain.items import ItemType
from atrium.metadata.artwork import (
    ArtworkResult,
    ImageKind,
    describe,
    find_artwork,
    tag_of,
    with_embedded,
)
from atrium.metadata.tags import EmbeddedArt

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "metadata" / "artwork"

#: The smallest valid PNG - one pixel - for cases that need bytes rather than a fixture.
ONE_PIXEL = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080600000"
    "01f15c4890000000a49444154789c6300010000050001"
)


def sized(result: ArtworkResult, kind: ImageKind) -> list[tuple[int, int]]:
    """The dimensions of every image of `kind`, in the order they were found."""
    return [(one.width, one.height) for one in result.files if one.kind is kind]


def only(result: ArtworkResult, kind: ImageKind) -> tuple[int, int] | None:
    found = sized(result, kind)
    return found[0] if found else None


# ----------------------------------------------------------------------------------------------
# Every name in the tables, one directory per fallback level
# ----------------------------------------------------------------------------------------------


def test_the_first_name_of_every_type_wins_when_all_fourteen_are_present() -> None:
    result = find_artwork(FIXTURES / "names-first", ItemType.MOVIE)
    assert only(result, ImageKind.PRIMARY) == (2, 3), "poster"
    assert only(result, ImageKind.LOGO) == (10, 4), "logo"
    assert only(result, ImageKind.BANNER) == (30, 5), "banner"
    assert only(result, ImageKind.DISC) == (9, 9), "disc, because this is a film"
    assert not result.warnings


def test_landscape_beats_thumb_which_is_the_opposite_of_the_specs_table() -> None:
    """Spec section 3.4 lists `thumb`, `landscape`. The reference tries `landscape` first
    `[source: MediaBrowser.LocalMetadata/Images/LocalImageProvider.cs:243-249 @ v10.11.11]`, and
    both files are present in this directory - so the dimensions say which rule is in force."""
    result = find_artwork(FIXTURES / "names-first", ItemType.MOVIE)
    assert only(result, ImageKind.THUMB) == (24, 14), "landscape, not thumb's 12x7"


def test_thumb_still_wins_when_landscape_is_absent(tmp_path: Path) -> None:
    """No fixture directory isolates it, because T2 built them from the spec's ordering."""
    shutil.copy(FIXTURES / "names-first" / "thumb.jpg", tmp_path / "thumb.jpg")
    assert only(find_artwork(tmp_path, ItemType.MOVIE), ImageKind.THUMB) == (12, 7)


def test_dropping_each_winner_lets_the_next_name_have_its_turn() -> None:
    second = find_artwork(FIXTURES / "names-second", ItemType.MOVIE)
    assert only(second, ImageKind.PRIMARY) == (4, 6), "folder"
    assert only(second, ImageKind.LOGO) == (20, 8), "clearlogo"
    assert only(second, ImageKind.DISC) == (18, 18), "cdart"

    third = find_artwork(FIXTURES / "names-third", ItemType.MOVIE)
    assert only(third, ImageKind.PRIMARY) == (6, 9), "cover"

    fourth = find_artwork(FIXTURES / "names-fourth", ItemType.MOVIE)
    assert only(fourth, ImageKind.PRIMARY) == (8, 12), "default"


def test_every_backdrop_family_contributes_rather_than_the_first_winning() -> None:
    """Backdrops are the one accumulating type. `fanart`, then `background`, then `backdrop` -
    the reference's order, and the index is the position in the list rather than any number in
    the file name."""
    result = find_artwork(FIXTURES / "names-first", ItemType.MOVIE)
    assert sized(result, ImageKind.BACKDROP) == [(16, 9), (48, 27), (32, 18)]
    assert [one.index for one in result.files if one.kind is ImageKind.BACKDROP] == [0, 1, 2]


# ----------------------------------------------------------------------------------------------
# The per-type Primary lists, which the spec's table does not have
# ----------------------------------------------------------------------------------------------


def test_a_music_album_prefers_folder_over_poster(tmp_path: Path) -> None:
    """Because that is what every ripper writes. One list for everything would file a
    correctly-named album cover behind a poster somebody dropped in later."""
    for name in ("poster.jpg", "folder.jpg"):
        shutil.copy(FIXTURES / "names-first" / name, tmp_path / name)
    assert only(find_artwork(tmp_path, ItemType.MUSIC_ALBUM), ImageKind.PRIMARY) == (4, 6)
    assert only(find_artwork(tmp_path, ItemType.MOVIE), ImageKind.PRIMARY) == (2, 3)


@pytest.mark.parametrize(
    ("kind", "name"),
    [
        (ItemType.MUSIC_ALBUM, "albumart"),
        (ItemType.MUSIC_ALBUM, "jacket"),
        (ItemType.SERIES, "show"),
        (ItemType.MOVIE, "movie"),
    ],
)
def test_the_names_only_one_type_answers_to(tmp_path: Path, kind: ItemType, name: str) -> None:
    """Four names the spec's table does not have at all, each recognised by exactly one type."""
    shutil.copy(FIXTURES / "names-first" / "poster.jpg", tmp_path / f"{name}.jpg")
    assert only(find_artwork(tmp_path, kind), ImageKind.PRIMARY) == (2, 3)
    other = ItemType.EPISODE if kind is not ItemType.EPISODE else ItemType.MOVIE
    assert only(find_artwork(tmp_path, other), ImageKind.PRIMARY) is None


def test_a_music_album_prefers_cdart_and_a_film_prefers_disc(tmp_path: Path) -> None:
    for name in ("disc.jpg", "cdart.jpg"):
        shutil.copy(FIXTURES / "names-first" / name, tmp_path / name)
    assert only(find_artwork(tmp_path, ItemType.MUSIC_ALBUM), ImageKind.DISC) == (18, 18)
    assert only(find_artwork(tmp_path, ItemType.MOVIE), ImageKind.DISC) == (9, 9)


def test_a_film_also_answers_to_discart(tmp_path: Path) -> None:
    shutil.copy(FIXTURES / "names-first" / "disc.jpg", tmp_path / "discart.jpg")
    assert only(find_artwork(tmp_path, ItemType.MOVIE), ImageKind.DISC) == (9, 9)
    assert only(find_artwork(tmp_path, ItemType.MUSIC_ALBUM), ImageKind.DISC) is None


def test_an_episode_a_track_and_a_person_get_a_primary_and_nothing_else() -> None:
    """The reference gives none of the three a logo, a banner, a backdrop or a disc."""
    for kind in (ItemType.EPISODE, ItemType.AUDIO, ItemType.PERSON):
        result = find_artwork(FIXTURES / "names-first", kind)
        assert {one.kind for one in result.files} == {ImageKind.PRIMARY}, kind


# ----------------------------------------------------------------------------------------------
# Numbered backdrops
# ----------------------------------------------------------------------------------------------


def test_numbered_backdrops_stop_after_three_consecutive_misses() -> None:
    """The fixture holds `fanart`, `fanart-1`, `fanart-2`, `fanart3` and `fanart-10`.

    Three are found. The other two are not, and **both absences are the measured rule rather than
    a bug**: `fanart3` without a dash belongs to the `backdrop` family's naming and not to
    `fanart`'s, and `fanart-10` is past the three consecutive misses at 3, 4 and 5. T2 built this
    directory expecting a lexicographic-versus-numeric trap; the real rule turned out to be a
    different one, and the fixture proves it just as well.
    """
    result = find_artwork(FIXTURES / "numbered-backdrops", ItemType.MOVIE)
    assert sized(result, ImageKind.BACKDROP) == [(16, 9), (17, 9), (18, 9)]


def test_a_gap_of_one_does_not_end_the_scan(tmp_path: Path) -> None:
    """Stopping at the first gap would lose every backdrop after a deleted one."""
    source = FIXTURES / "names-first" / "fanart.jpg"
    for name in ("fanart.jpg", "fanart-1.jpg", "fanart-3.jpg", "fanart-4.jpg"):
        shutil.copy(source, tmp_path / name)
    result = find_artwork(tmp_path, ItemType.MOVIE)
    assert len(sized(result, ImageKind.BACKDROP)) == 4


def test_the_backdrop_family_numbers_without_a_dash(tmp_path: Path) -> None:
    """`backdrop1`, not `backdrop-1` - the one family that differs, and the reference's own
    inconsistency rather than ours."""
    source = FIXTURES / "names-first" / "backdrop.jpg"
    for name in ("backdrop.jpg", "backdrop1.jpg", "backdrop2.jpg"):
        shutil.copy(source, tmp_path / name)
    assert len(sized(find_artwork(tmp_path, ItemType.MOVIE), ImageKind.BACKDROP)) == 3


def test_an_extrafanart_folder_is_taken_whole(tmp_path: Path) -> None:
    extra = tmp_path / "extrafanart"
    extra.mkdir()
    for name in ("one.jpg", "two.jpg"):
        shutil.copy(FIXTURES / "names-first" / "fanart.jpg", extra / name)
    assert len(sized(find_artwork(tmp_path, ItemType.MOVIE), ImageKind.BACKDROP)) == 2


def test_the_same_file_reached_by_two_names_is_associated_once(tmp_path: Path) -> None:
    """`fanart.jpg` is in the `fanart` family and `extrafanart/` may hold it too."""
    shutil.copy(FIXTURES / "names-first" / "fanart.jpg", tmp_path / "fanart.jpg")
    extra = tmp_path / "extrafanart"
    extra.mkdir()
    shutil.copy(FIXTURES / "names-first" / "fanart.jpg", extra / "fanart.jpg")
    assert len(sized(find_artwork(tmp_path, ItemType.MOVIE), ImageKind.BACKDROP)) == 2


# ----------------------------------------------------------------------------------------------
# Extensions and case
# ----------------------------------------------------------------------------------------------


def test_all_four_extensions_are_matched_in_any_case() -> None:
    """`poster.JPG`, `fanart.jpeg`, `logo.PNG`, `banner.webp`, `disc.Jpeg`."""
    result = find_artwork(FIXTURES / "extensions", ItemType.MOVIE)
    assert only(result, ImageKind.PRIMARY) == (2, 3)
    assert only(result, ImageKind.LOGO) == (10, 4)
    assert only(result, ImageKind.BANNER) == (30, 5)
    assert only(result, ImageKind.DISC) == (9, 9)
    assert sized(result, ImageKind.BACKDROP) == [(16, 9)]


def test_a_file_with_an_extension_the_tables_do_not_cover_is_not_an_image(tmp_path: Path) -> None:
    shutil.copy(FIXTURES / "names-first" / "poster.jpg", tmp_path / "poster.bmp")
    assert find_artwork(tmp_path, ItemType.MOVIE).files == ()


# ----------------------------------------------------------------------------------------------
# The per-item names
# ----------------------------------------------------------------------------------------------


def test_a_per_item_poster_beats_the_folders() -> None:
    """A folder holding two films has one `poster.jpg` that can only be one of them."""
    result = find_artwork(FIXTURES / "per-item", ItemType.MOVIE, stem="Film (1999)")
    assert only(result, ImageKind.PRIMARY) == (3, 5), "Film (1999)-poster.jpg"


def test_the_bare_stem_beats_everything_including_the_prefixed_name(tmp_path: Path) -> None:
    """`Film (1999).jpg`, which spec section 3.4's table does not name at all and the reference
    tries **first** `[source: MediaBrowser.LocalMetadata/Images/LocalImageProvider.cs:285-291 @
    v10.11.11]`."""
    shutil.copy(FIXTURES / "names-first" / "cover.jpg", tmp_path / "Film (1999).jpg")
    shutil.copy(FIXTURES / "names-first" / "poster.jpg", tmp_path / "Film (1999)-poster.jpg")
    shutil.copy(FIXTURES / "names-first" / "folder.jpg", tmp_path / "poster.jpg")
    result = find_artwork(tmp_path, ItemType.MOVIE, stem="Film (1999)")
    assert only(result, ImageKind.PRIMARY) == (6, 9), "the bare stem"


def test_without_a_stem_the_folder_names_answer() -> None:
    result = find_artwork(FIXTURES / "per-item", ItemType.MOVIE)
    assert only(result, ImageKind.PRIMARY) == (2, 3), "poster.jpg"


def test_a_per_item_backdrop_is_found_too(tmp_path: Path) -> None:
    shutil.copy(FIXTURES / "names-first" / "fanart.jpg", tmp_path / "Film (1999)-fanart.jpg")
    result = find_artwork(tmp_path, ItemType.MOVIE, stem="Film (1999)")
    assert sized(result, ImageKind.BACKDROP) == [(16, 9)]


# ----------------------------------------------------------------------------------------------
# Dimensions and tags are never optional
# ----------------------------------------------------------------------------------------------


def test_a_file_that_is_not_an_image_is_skipped_with_a_warning_and_the_next_name_wins() -> None:
    """Readability is part of the first-match rule rather than a check after it: one corrupt
    `poster.jpg` must not leave an item with no image while a good `folder.png` sits beside it."""
    result = find_artwork(FIXTURES / "unreadable", ItemType.MOVIE)
    assert only(result, ImageKind.PRIMARY) == (4, 6), "folder.png"
    assert len(result.warnings) == 1
    assert "poster.jpg" in result.warnings[0]


def test_no_association_ever_lacks_its_dimensions_or_its_tag() -> None:
    """005 emits `PrimaryImageAspectRatio` and `ImageTags` from these rows before 006 serves a
    byte, so a row missing either makes an item's aspect ratio silently absent."""
    for directory in sorted(FIXTURES.iterdir()):
        if not directory.is_dir():
            continue
        for image in find_artwork(directory, ItemType.MOVIE).files:
            assert image.width > 0 and image.height > 0, image
            assert len(image.tag) == 32, image
            assert image.tag == image.tag.lower()
            int(image.tag, 16)


def test_the_tag_is_the_same_for_the_same_bytes_wherever_they_sit() -> None:
    """006 AC-2's ancestor: a rescan of an unchanged file must not change its tag, or every
    client re-downloads every image. The fixture tree deliberately holds the same bytes under
    several directories."""
    first = find_artwork(FIXTURES / "names-first", ItemType.MOVIE)
    second = find_artwork(FIXTURES / "names-second", ItemType.MOVIE)
    folder_in_second = only(second, ImageKind.PRIMARY)
    assert folder_in_second == (4, 6)
    tags = {one.tag for one in (*first.files, *second.files) if (one.width, one.height) == (4, 6)}
    assert len(tags) == 1, "identical bytes, one tag"


def test_the_tag_changes_when_the_bytes_do(tmp_path: Path) -> None:
    poster = tmp_path / "poster.jpg"
    shutil.copy(FIXTURES / "names-first" / "poster.jpg", poster)
    before = only_tag(find_artwork(tmp_path, ItemType.MOVIE))
    shutil.copy(FIXTURES / "names-first" / "cover.jpg", poster)
    assert only_tag(find_artwork(tmp_path, ItemType.MOVIE)) != before


def only_tag(result: ArtworkResult) -> str:
    return next(one.tag for one in result.files if one.kind is ImageKind.PRIMARY)


def test_rescanning_an_untouched_directory_produces_identical_associations() -> None:
    assert find_artwork(FIXTURES / "names-first", ItemType.MOVIE) == find_artwork(
        FIXTURES / "names-first", ItemType.MOVIE
    )


def test_the_tag_is_the_reference_width_and_derivation() -> None:
    """32 lowercase hex, the first sixteen bytes of the SHA-256 - the same shape as an item id."""
    import hashlib

    assert tag_of(b"abc") == hashlib.sha256(b"abc").hexdigest()[:32]


def test_describing_something_that_is_not_an_image_is_none_rather_than_an_exception(
    tmp_path: Path,
) -> None:
    plain = tmp_path / "poster.jpg"
    plain.write_text("not an image", encoding="utf-8")
    assert describe(plain) is None
    assert describe(tmp_path / "absent.jpg") is None


def test_a_directory_that_cannot_be_listed_is_a_warning_rather_than_a_failure(
    tmp_path: Path,
) -> None:
    result = find_artwork(tmp_path / "nowhere", ItemType.MOVIE)
    assert result.files == ()
    assert result.warnings


# ----------------------------------------------------------------------------------------------
# Embedded cover art
# ----------------------------------------------------------------------------------------------


def test_embedded_art_becomes_the_primary_when_no_file_based_one_exists(tmp_path: Path) -> None:
    result = with_embedded(find_artwork(tmp_path, ItemType.AUDIO), EmbeddedArt(ONE_PIXEL))
    assert only(result, ImageKind.PRIMARY) == (1, 1)
    assert result.files[0].path == Path(), "no path: the bytes live inside the audio file"


def test_a_file_based_primary_beats_the_embedded_one() -> None:
    """A user who drops a `folder.jpg` beside an album has overridden what the files carry, and a
    reader that preferred the embedded copy would make that edit do nothing."""
    on_disk = find_artwork(FIXTURES / "names-first", ItemType.MUSIC_ALBUM)
    result = with_embedded(on_disk, EmbeddedArt(ONE_PIXEL))
    assert only(result, ImageKind.PRIMARY) == (4, 6), "folder.jpg, not the embedded pixel"


def test_embedded_art_that_is_not_an_image_warns_rather_than_associating(tmp_path: Path) -> None:
    result = with_embedded(find_artwork(tmp_path, ItemType.AUDIO), EmbeddedArt(b"not an image"))
    assert result.files == ()
    assert result.warnings


def test_no_embedded_art_changes_nothing(tmp_path: Path) -> None:
    before = find_artwork(tmp_path, ItemType.AUDIO)
    assert with_embedded(before, None) == before


# ----------------------------------------------------------------------------------------------
# Nothing here writes
# ----------------------------------------------------------------------------------------------


def test_reading_every_fixture_directory_leaves_the_tree_byte_identical() -> None:
    """AC-15's ancestor, at module level, in the module most likely to break it: this is the one
    that opens image files."""
    import hashlib

    def digest() -> dict[str, str]:
        return {
            str(path.relative_to(FIXTURES)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(FIXTURES.rglob("*"))
            if path.is_file()
        }

    before = digest()
    for kind in ItemType:
        for directory in sorted(FIXTURES.iterdir()):
            if directory.is_dir():
                find_artwork(directory, kind, stem="Film (1999)")
    assert digest() == before
