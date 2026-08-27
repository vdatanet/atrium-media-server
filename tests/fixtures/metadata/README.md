# Metadata fixtures

Everything 004 *reads*. 003's fixture library is generated onto disk from a manifest because
nothing in that feature opens a file; these are checked-in bytes because every one of them exists
to be parsed, decoded or tagged, and a generator would only move the question of what the bytes
are somewhere else.

**Nothing here is anybody's work.** The sidecars are invented, the images are flat colour, the
audio is silence we generated. Fifty-six files, about 20 KB in total.

**The generation commands are below, exactly as they were run**, on the machine that produced the
committed bytes. They are a record, not a build step: nothing in the suite runs them, and
re-running them on a different `ffmpeg` will produce different bytes for the same picture. That is
fine — the bytes in the repository are the fixture.

---

## `nfo/` — sidecars

Written by hand. Every one opens with a comment saying it is synthetic, so the answer to "is this
somebody's metadata?" is in the first line rather than inferred.

| File | What it is for |
|---|---|
| `movie-full.nfo` | Every field [plan §6.2](../../../specs/004-metadata-resolution/plan.md#62-sidecars) maps, once. Three actors in billing order; two studios; two tags; both `uniqueid` forms. One genre element reads `Science Fiction / Fantasy` — a single genre containing ` / `, which must **not** be split |
| `movie-sparse.nfo` | Title and year only, plus `<plot></plot>` and a whitespace-only `<tagline>`: the two shapes [spec §3.1](../../../specs/004-metadata-resolution/spec.md#31-the-provider-model) says are not values, so the next provider in the chain still gets its turn |
| `movie-ids.nfo` | Provider identifiers and nothing else — the AC-3 subject, where identification must be skipped entirely |
| `movie-malformed.nfo` | An unclosed `<title>`. The plain parse-error path |
| `movie-entity-internal.nfo` | A document type declaration defining an entity, used in a value |
| `movie-entity-external.nfo` | A document type declaration defining an **external** entity — the XXE shape |
| `movie-entity-bomb.nfo` | Five levels of ten nested entities: 400 bytes that expand to about 200 KB |
| `tvshow.nfo`, `season.nfo`, `episode.nfo`, `album.nfo`, `artist.nfo` | One per remaining row of [spec §3.2](../../../specs/004-metadata-resolution/spec.md#32-nfo-sidecars)'s discovery table. The tests that exercise *discovery* copy these into a tree of their own making; nothing here presumes a layout |

### What the three entity fixtures measured, and why there are three

The plan said stdlib `ElementTree` "refuses DTDs and entity definitions outright, which turns the
whole XXE class into the malformed-sidecar path". Measured on Python 3.14.6 / expat 1.3.0, that is
wrong three ways, and the three files pin each one:

| Fixture | What the stdlib parser does by default |
|---|---|
| `movie-entity-internal.nfo` | **Parses, and expands the entity.** The value arrives with the entity's text substituted in |
| `movie-entity-external.nfo` | **Raises** `ParseError: undefined entity` — no external entity is ever fetched, so file disclosure is impossible, but by failing rather than by refusing the declaration |
| `movie-entity-bomb.nfo` | **Parses, and expands 400 bytes into 200,000 characters.** Exponential entity expansion is not prevented at all |

The bomb is deliberately modest. A nine-level one is four lines longer and would let a careless
test exhaust a machine; five levels demonstrate that the growth is exponential, which is the whole
claim. [Plan §6.2](../../../specs/004-metadata-resolution/plan.md#62-sidecars) now says what
actually happens and what T5 has to implement to make the plan's original sentence true.

**The size cap has no fixture here**, on purpose: a file over the cap is megabytes, and this tree
is 20 KB. The test that exercises it writes one into a temporary directory.

---

## `artwork/` — local artwork

Flat-colour rectangles. **Every name gets a distinct size**, so a test can say which file won a
type by looking at the dimensions rather than at the path — which is the thing under test.

| Directory | What it is for |
|---|---|
| `names-first/` | Every one of the fourteen names in [plan §6.4](../../../specs/004-metadata-resolution/plan.md#64-local-artwork)'s tables, present at once. The first name of each type wins |
| `names-second/` | The same directory with those six winners removed, so `folder`, `backdrop`, `clearlogo`, `landscape` and `cdart` get their turn |
| `names-third/` | And again: `cover` and `background` |
| `names-fourth/` | And again: `default`, the last Primary name |
| `numbered-backdrops/` | `fanart`, `fanart-1`, `fanart-2`, `fanart3`, `fanart-10` — both numbering forms, and a **10 that must sort after the 3**, which a lexicographic sort gets wrong |
| `extensions/` | The four extensions in mixed case: `poster.JPG`, `fanart.jpeg`, `logo.PNG`, `banner.webp`, `disc.Jpeg` |
| `per-item/` | `Film (1999)-poster.jpg` beside a `poster.jpg`, for the per-item name |
| `unreadable/` | A `poster.jpg` that is a line of text, beside a `folder.png` that is a real image: the skip-with-a-warning path, and proof that the fallback still resolves |

Sizes, one per name: `poster` 2×3, `folder` 4×6, `cover` 6×9, `default` 8×12, `fanart` 16×9,
`backdrop` 32×18, `background` 48×27, `logo` 10×4, `clearlogo` 20×8, `thumb` 12×7,
`landscape` 24×14, `banner` 30×5, `disc` 9×9, `cdart` 18×18, and `<stem>-poster` 3×5.

The same name in two directories is the same bytes, which is deliberate: identical bytes must
produce an identical content tag wherever they sit.

```sh
# a flat colour of an exact size, one frame, no encoder metadata
gen() {
  ffmpeg -hide_banner -loglevel error -y -bitexact \
    -f lavfi -i "color=c=${4}:s=${2}x${3}:d=1" -frames:v 1 -update 1 "${1}"
}
gen names-first/poster.jpg  2 3  0x101010     # ... once per name and size above
cp names-first/folder.jpg names-second/       # the later directories are copies

# webp, which this ffmpeg build cannot encode
ffmpeg -hide_banner -loglevel error -y -bitexact \
  -f lavfi -i "color=c=0x004400:s=30x5:d=1" -frames:v 1 -update 1 banner-src.png
cwebp -quiet -lossless banner-src.png -o extensions/banner.webp

# the file that is not an image
printf 'atrium synthetic fixture - deliberately not an image\n' > unreadable/poster.jpg
```

`${2}` and `${4}`, not `$2` and `$4`: in zsh, `$4:s=` is a substitution *modifier* on `$4`, and
the first run of this script silently produced fourteen 320×240 images — lavfi's default size —
because everything after `:s=` had been eaten. Verifying that an edit landed applies to fixtures
too.

---

## `audio/` — the four template containers

Silence. Four containers covering the three tag systems [plan §6.3](../../../specs/004-metadata-resolution/plan.md#63-embedded-tags)
names: Vorbis comments (`.flac`, `.ogg`), ID3 (`.mp3`) and MP4 atoms (`.m4a`).

**They carry no tags at all** — not even the encoder tag `ffmpeg` writes, which names its own
version and would have put a tool's version number inside a checked-in fixture. Each test copies
a template and writes the tags it wants with mutagen, so a case is one file's worth of tags on a
known, empty container.

| File | Bytes | Duration |
|---|---|---|
| `template.flac` | 1,217 | 0.25 s |
| `template.mp3` | 2,480 | 0.29 s |
| `template.m4a` | 889 | 0.27 s |
| `template.ogg` | 3,773 | 0.25 s |

```sh
# -metadata_header_padding 0 matters: the default 8 KB of FLAC padding made that template
# forty times its own size. -bitexact and -map_metadata -1 are not enough on their own -
# each muxer still writes its own encoder tag, which is why the second step exists.
ffmpeg -bitexact -f lavfi -i anullsrc=r=44100:cl=mono   -t 0.25 -c:a flac       -map_metadata -1 -metadata_header_padding 0 template.flac
ffmpeg -bitexact -f lavfi -i anullsrc=r=44100:cl=mono   -t 0.25 -c:a libmp3lame -map_metadata -1 template.mp3
ffmpeg -bitexact -f lavfi -i anullsrc=r=44100:cl=mono   -t 0.25 -c:a aac        -map_metadata -1 template.m4a
ffmpeg -bitexact -f lavfi -i anullsrc=r=44100:cl=stereo -t 0.25 -c:a vorbis -strict -2 -map_metadata -1 template.ogg
```

```python
# then, once, to remove the encoder tag each muxer added anyway
from mutagen.flac import FLAC
from mutagen.oggvorbis import OggVorbis
from mutagen.mp4 import MP4
from mutagen.mp3 import MP3

f = FLAC("template.flac"); f.delete(); f.clear_pictures(); f.save()
o = OggVorbis("template.ogg"); o.delete(); o.save()
m = MP4("template.m4a"); m.delete(); m.save()
MP3("template.mp3").delete()
```

The Ogg template is **stereo** and the other three are mono, for a reason worth knowing before
regenerating it: this `ffmpeg` has no `libvorbis`, and its own Vorbis encoder refuses anything
that is not two channels.

---

## Regenerating the inventory

`inventory.py` holds every file here by digest, and
[`tests/metadata/test_fixture_tree.py`](../../metadata/test_fixture_tree.py) holds the tree to it
in both directions. After a deliberate change:

```sh
uv run python - <<'PY'
import hashlib, pathlib
root = pathlib.Path("tests/fixtures/metadata")
for p in sorted(root.rglob("*")):
    if not p.is_file() or p.suffix == ".py" or p.name == "README.md" or "__pycache__" in p.parts:
        continue
    b = p.read_bytes()
    print(f'    "{p.relative_to(root)}": "{hashlib.sha256(b).hexdigest()[:32]}",')
PY
```

003 kept the same promise by committing nothing at all, and
[its guard](../../library/test_fixture_library.py) still does for its own tree — 004 T2 narrowed
that test to `tests/fixtures/library` and put the other half here, because a feature whose subject
is *reading* files cannot generate them from a manifest.

## What the containers still carry

All four audio templates hold their muxer's version in a header field that belongs to the format
rather than to the tags — the vendor string of a Vorbis comment block, the `Info` frame of an MP3,
an atom in an M4A. A tag reader never returns those, so no test case can see one, and rewriting
them would mean re-deriving each format's length fields for nothing. What matters is that a tag
reader finds **no fields**, which needs a tag reader: T7 asserts it with mutagen, and until then
the guard here asserts the field names are absent from the bytes.
