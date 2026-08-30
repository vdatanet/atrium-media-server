# SPDX-License-Identifier: GPL-3.0-or-later
"""What a delivery response calls itself: a container, and the `Content-Type` it is labelled with.

On a `static=true` request the label is the **only** thing the path's container decides
(behaviours section 2.20): `stream.mkv?static=true` on an mp4 film answers the mp4 bytes behind
`video/x-matroska`, byte-identical to the unsuffixed route. So this table is a wire fact rather
than a fact about any file, and getting an entry wrong is a difference a client sees on a request
whose body is right.

**Measured, not transcribed.** Every row below was read off the reference by asking a static route
for it - the whole of `library/walker.py`'s admitted extension set, video and audio, plus the two
an HLS client names `[probe: tools/probe_range_matrix.py, Jellyfin 10.11.11, 2026-08-29]`. That
matters twice over: copying the reference's own table would be copying its code (Principle IV),
and the table is not guessable. Six rows nobody would have written from first principles:

* `.mts` is **`model/vnd.mts`** - a 3-D model type, on a video container;
* `.mpc` is **`application/vnd.mophun.certificate`**;
* `.rmvb` is `application/vnd.rn-realmedia-vbr`, not a `video/` type at all;
* `.opus` and `.oga` are both `audio/ogg`, never `audio/opus`;
* `.dff` and `.alac` are both `audio/mp4`, where `.dsf` beside them is `audio/dsf`;
* `.ogv` is `video/ogg` while `.ogg` is `audio/ogg`.

**A container this table does not know is not an error.** The reference resolves the label from
the requested container first and falls back to the *file's own* extension when that names
nothing: `stream.banana?static=true` on an mp4 answers `video/mp4`, measured, and the fallback of
the fallback is `application/octet-stream` `[source:
Jellyfin.Api/Controllers/VideosController.cs:470,
MediaBrowser.Controller/MediaEncoding/EncodingJobInfo.cs:545-558 @ v10.11.11]`.

## The subtitle rows, and the two spellings that deliberately have none

011 plan section 6.8 sends the fetch formats here rather than to a second table, and it is the
same table on the reference too: a `static=true` delivery and a subtitle fetch both resolve their
label through one lookup on `file.{container}` `[source:
Jellyfin.Api/Controllers/SubtitleController.cs:261,274,
MediaBrowser.Model/Net/MimeTypes.cs:158-181 @ v10.11.11]`. `.ass` and `.ssa` are an explicit
override in that file; the other four fall through to a third-party table this project cannot
cite. **All six are measured** - `text/vtt`, `application/x-subrip`, `text/x-ssa` on both of `ass`
and `ssa`, `application/json` on both of `json` and its alias `js`, and `application/ttml+xml`
`[probe: tools/probe_subtitle_delivery.py, Jellyfin 10.11.11, 2026-08-30]`.

**`subrip` and `webvtt` have a writer and no row, on both servers - and they still answer.** They
are the two spellings 011's writable set carries that the reference's own label lookup cannot
answer, and the first draft of this paragraph concluded it therefore fails on the label. It does
not: a lookup with no row and no default hands back nothing, and the framework's file result
**defaults the content type**. Measured at 011 T7: both answer `200` with the whole rendered
document under `application/octet-stream`, which is `DEFAULT_MEDIA_TYPE` below
`[probe: tools/probe_subtitle_delivery.py, Jellyfin 10.11.11, 2026-08-30]`. So the gap is still
reproduced by leaving them out - the fetch route falls through to the default and lands on the
same string - and adding a row would be choosing a label where the reference chooses none.
"""

from __future__ import annotations

from pathlib import PurePosixPath

#: The label a container nobody recognises gets, on both sides of the fallback.
DEFAULT_MEDIA_TYPE = "application/octet-stream"

#: Container (no leading dot, lowercase) to `Content-Type`, exactly as the reference answers it.
#: One dictionary rather than one per route family: the reference resolves the label from the
#: container alone, so `stream.mp3` on the video route is `audio/mpeg` there as well.
MEDIA_TYPES: dict[str, str] = {
    # Video containers - `library/walker.py`'s set, in its order.
    "mkv": "video/x-matroska",
    "mp4": "video/mp4",
    "avi": "video/x-msvideo",
    "ts": "video/mp2t",
    "m4v": "video/x-m4v",
    "mov": "video/quicktime",
    "wmv": "video/x-ms-wmv",
    "flv": "video/x-flv",
    "webm": "video/webm",
    "mpg": "video/mpeg",
    "mpeg": "video/mpeg",
    "m2ts": "video/m2ts",
    "mts": "model/vnd.mts",
    "vob": "video/x-ms-vob",
    "ogv": "video/ogg",
    "divx": "video/divx",
    "3gp": "video/3gpp",
    "rmvb": "application/vnd.rn-realmedia-vbr",
    "asf": "video/x-ms-asf",
    # Audio containers.
    "flac": "audio/flac",
    "m4a": "audio/mp4",
    "dsf": "audio/dsf",
    "mp3": "audio/mpeg",
    "ogg": "audio/ogg",
    "oga": "audio/ogg",
    "opus": "audio/ogg",
    "wav": "audio/wav",
    "aac": "audio/aac",
    "wma": "audio/x-ms-wma",
    "aiff": "audio/x-aiff",
    "aif": "audio/x-aiff",
    "ape": "audio/x-ape",
    "dff": "audio/mp4",
    "mka": "audio/x-matroska",
    "alac": "audio/mp4",
    "wv": "audio/x-wavpack",
    "mpc": "application/vnd.mophun.certificate",
    # Named by every HLS client and held by no library, so 008's playlist routes read them here
    # rather than writing a second table.
    "m3u8": "application/vnd.apple.mpegurl",
    # The six formats 011's fetch routes write. `ass` and `ssa` are the reference's own override
    # `[source: MediaBrowser.Model/Net/MimeTypes.cs:82-83 @ v10.11.11]`; the other four fall
    # through to the third-party table behind it. All six measured `[probe:
    # tools/probe_subtitle_delivery.py, Jellyfin 10.11.11, 2026-08-30]`, `ttml` at 011 T7.
    # `subrip` and `webvtt` have no row on purpose - see the docstring.
    "ass": "text/x-ssa",
    "ssa": "text/x-ssa",
    "srt": "application/x-subrip",
    "vtt": "text/vtt",
    "json": "application/json",
    "ttml": "application/ttml+xml",
}


def media_type_of(container: str | None) -> str | None:
    """The label for one container, or `None` where the table has no row for it.

    `None` rather than the default, because the caller has a second thing to ask before falling
    back - the file's own extension - and a function that defaulted here would swallow it.
    """
    if not container:
        return None
    return MEDIA_TYPES.get(container.lstrip(".").lower())


def label_for(requested: str | None, relative_path: str) -> str:
    """The `Content-Type` a static response carries: the requested container, then the file's own.

    The reference's two-step, in its order: the container the URL named, the extension of the file
    being served, and `application/octet-stream` if neither names anything. A request for a
    container nobody has heard of therefore still gets an honest label, because the bytes are the
    file's and so, in that case, is the label.
    """
    from_request = media_type_of(requested)
    if from_request is not None:
        return from_request
    from_file = media_type_of(PurePosixPath(relative_path).suffix)
    return from_file if from_file is not None else DEFAULT_MEDIA_TYPE


__all__ = ["DEFAULT_MEDIA_TYPE", "MEDIA_TYPES", "label_for", "media_type_of"]
