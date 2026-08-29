#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""What does the reference answer for a media source nothing has successfully opened - on a
negotiation, on a listing, and on the negotiation *after* the file became readable?

specs/012-negotiation-inputs/spec.md opens with four questions this probe answers (OQ-1, OQ-2,
OQ-3, OQ-9), and its reading of the reference predicts that the state does not exist there at all:
the negotiation is documented as forcing a metadata refresh with probing when the first source
carries no stream of the item's own kind
`[source: Emby.Server.Implementations/Library/MediaSourceManager.cs:170-189 @ v10.11.11]`, while
the listing reads the sources without it
`[source: Emby.Server.Implementations/Dto/DtoService.cs:261 @ v10.11.11]`. A reading predicts; it
does not measure.

**The fixture is a subtraction, and it cannot be found - only built.** Every item in a real library
has been probed, because the scan that created it probed it; the state exists only where the probe
*failed*. So this probe builds a library out of files ffprobe cannot read - a zero-length one, a
4 KiB one that is not a container at all - beside two it can, scans it, and measures the six
answers. One of the unreadable files is then **replaced with a valid one behind the server's back**,
which is what makes OQ-1 and OQ-9 answerable: the next negotiation is the only thing that has ever
looked at those bytes.

Because the fixture has to be on the server's own disk, this probe cannot run against a remote
reference. Point it at a local Jellyfin 10.11.11 whose media directory this machine can write:

    docker run -d --name jf -p 8097:8096 \\
        -v "$PWD/fixture:/media" jellyfin/jellyfin:10.11.11
    #  … complete the startup wizard, then …
    python3 tools/probe_uninspected_source.py http://127.0.0.1:8097 -u admin \\
        --allow-writes --fixture-root "$PWD/fixture" --server-root /media

`--fixture-root` is where this machine writes; `--server-root` is where that same directory appears
inside the server, and defaults to `--fixture-root` when the two are the same host. The probe
creates two libraries, scans, measures, then deletes both libraries and the files it wrote -
including on failure. It writes nothing outside the directory it is given.

Needs `ffmpeg` on PATH to build the two readable files.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from _playback import base_profile
from _probe import Probe, ProbeError, Server, main

#: The prefix every directory and library this probe creates carries, so that an interrupted run
#: is recognisable and can be removed by hand from the server's own dashboard.
PREFIX = "atrium-probe-uninspected"

#: **A run gets a directory nothing has used before, and this is not tidiness.** Deleting a virtual
#: folder does not take the item rows with it, and an item's identifier is derived from its path -
#: so a second run writing the same paths inherits the first run's *streams*, and the file this
#: probe deliberately leaves unreadable arrives at the scan already annotated. That is exactly the
#: false pass `freshened` exists to prevent one route away, found here the same way: by running the
#: probe twice.
RUN_ID = uuid.uuid4().hex[:8]
MOVIE_LIBRARY = f"{PREFIX}-video-{RUN_ID}"
MUSIC_LIBRARY = f"{PREFIX}-audio-{RUN_ID}"
FIXTURE_DIR = f"{PREFIX}-{RUN_ID}"

#: A profile that plays nothing this fixture contains, so every answer is attributable to the
#: source rather than to the profile: an mkv is not mp4, and the ladder has to decide.
VIDEO_PROFILE = base_profile(
    [{"Container": "mp4", "Type": "Video", "VideoCodec": "h264", "AudioCodec": "aac"}]
)
AUDIO_PROFILE: dict[str, Any] = {
    "MaxStreamingBitrate": 120_000_000,
    "DirectPlayProfiles": [{"Container": "mp4", "Type": "Audio", "AudioCodec": "aac"}],
    "TranscodingProfiles": [
        {
            "Container": "mp3",
            "Type": "Audio",
            "AudioCodec": "mp3",
            "Protocol": "http",
            "Context": "Streaming",
        }
    ],
    "CodecProfiles": [],
    "ContainerProfiles": [],
    "SubtitleProfiles": [],
}


# --------------------------------------------------------------------------------------------
# The fixture
# --------------------------------------------------------------------------------------------


def _ffmpeg(arguments: list[str]) -> None:
    binary = shutil.which("ffmpeg")
    if not binary:
        raise ProbeError(
            "ffmpeg is not on PATH, and this probe has to build two readable files: the whole "
            "question is what a negotiation answers once bytes it never saw become valid"
        )
    result = subprocess.run(  # noqa: S603 - arguments are this probe's own constants
        [binary, "-v", "error", "-y", *arguments], capture_output=True, check=False
    )
    if result.returncode != 0:
        raise ProbeError(f"ffmpeg failed: {result.stderr[:200]!r}")


def build_fixture(root: Path) -> dict[str, Path]:
    """Six files: two readable, three ffprobe refuses, one that changes its mind later.

    The names carry their own explanation, because they end up in a server's library and an
    operator reading a dashboard deserves to know what they are looking at.
    """
    movies = root / "movies"
    music = root / "music"
    for name in (
        "Atrium Probe Readable (2001)",
        "Atrium Probe Vanishing (2002)",
        "Atrium Probe Unreadable (2003)",
        "Atrium Probe Empty (2004)",
        "Atrium Probe Truncated (2005)",
        "Atrium Probe Latent (2006)",
    ):
        (movies / name).mkdir(parents=True, exist_ok=True)
    (music / "Atrium Probe Artist" / "Atrium Probe Album").mkdir(parents=True, exist_ok=True)

    readable = movies / "Atrium Probe Readable (2001)" / "Atrium Probe Readable (2001).mkv"
    _ffmpeg(
        [
            "-f", "lavfi", "-i", "testsrc=size=320x240:rate=24:duration=6",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(readable),
        ]
    )  # fmt: skip
    album = music / "Atrium Probe Artist" / "Atrium Probe Album"
    track = album / "01 Atrium Probe Track.mp3"
    _ffmpeg(
        ["-f", "lavfi", "-i", "sine=frequency=440:duration=6", "-c:a", "libmp3lame", str(track)]
    )

    vanishing = movies / "Atrium Probe Vanishing (2002)" / "Atrium Probe Vanishing (2002).mkv"
    shutil.copyfile(readable, vanishing)

    unreadable = movies / "Atrium Probe Unreadable (2003)" / "Atrium Probe Unreadable (2003).mkv"
    latent = movies / "Atrium Probe Latent (2006)" / "Atrium Probe Latent (2006).mkv"
    noise = os.urandom(4096)
    unreadable.write_bytes(noise)
    latent.write_bytes(noise)

    #: The music client's half of section 2.2, and the reason it is a separate file rather than
    #: the same one: an audio item reaches a different branch of the ladder from a video one.
    broken_track = album / "02 Atrium Probe Broken.mp3"
    broken_track.write_bytes(os.urandom(4096))

    empty = movies / "Atrium Probe Empty (2004)" / "Atrium Probe Empty (2004).mkv"
    empty.write_bytes(b"")

    truncated = movies / "Atrium Probe Truncated (2005)" / "Atrium Probe Truncated (2005).mkv"
    truncated.write_bytes(readable.read_bytes()[:1024])

    return {
        "readable": readable,
        "vanishing": vanishing,
        "unreadable": unreadable,
        "empty": empty,
        "truncated": truncated,
        "latent": latent,
        "track": track,
        "broken_track": broken_track,
    }


def add_library(server: Server, name: str, collection: str, path: str) -> None:
    body = {
        "LibraryOptions": {
            "EnableInternetProviders": False,
            "EnableRealtimeMonitor": False,
            "SaveLocalMetadata": False,
            "EnableChapterImageExtraction": False,
            "ExtractChapterImagesDuringLibraryScan": False,
            "EnableLUFSScan": False,
            "PathInfos": [{"Path": path}],
        }
    }
    status, _, payload = server.post_raw(
        "/Library/VirtualFolders",
        body=body,
        name=name,
        collectionType=collection,
        paths=path,
        refreshLibrary="false",
    )
    if status not in (200, 204):
        raise ProbeError(f"could not create the {name} library: {status} {payload[:160]!r}")


def scan_and_wait(server: Server, timeout: int = 300) -> float:
    """Run the library scan and wait for it, because everything after this reads its result."""
    started = time.monotonic()
    status, _, payload = server.post_raw("/Library/Refresh")
    if status not in (200, 204):
        raise ProbeError(f"POST /Library/Refresh answered {status}: {payload[:160]!r}")
    time.sleep(2)
    while time.monotonic() - started < timeout:
        running = [t for t in server.get("/ScheduledTasks") if t.get("Key") == "RefreshLibrary"]
        if running and running[0].get("State") == "Idle":
            return round(time.monotonic() - started, 1)
        time.sleep(2)
    raise ProbeError("the library scan did not finish inside the timeout")


def items_by_path(server: Server) -> dict[str, dict[str, Any]]:
    found = server.get(
        "/Items",
        UserId=server.user_id,
        IncludeItemTypes="Movie,Audio",
        Recursive="true",
        Limit=200,
        Fields="MediaSources,Path",
    )
    return {row.get("Path") or "": row for row in found.get("Items", [])}


# --------------------------------------------------------------------------------------------
# Reading one answer
# --------------------------------------------------------------------------------------------


def _shape(source: dict[str, Any]) -> str:
    streams = source.get("MediaStreams") or []
    flags = "/".join(
        str(source.get(key))
        for key in ("SupportsDirectPlay", "SupportsDirectStream", "SupportsTranscoding")
    )
    return (
        f"streams={len(streams)}, RunTimeTicks={source.get('RunTimeTicks')}, "
        f"Bitrate={source.get('Bitrate')}, Container={source.get('Container')!r}, "
        f"Size={source.get('Size')}, flags={flags}, "
        f"{'url' if source.get('TranscodingUrl') else 'no url'}"
    )


def listing_source(server: Server, item_id: str) -> dict[str, Any]:
    item = server.get(f"/Items/{item_id}", userId=server.user_id)
    return ((item.get("MediaSources") or [{}]) or [{}])[0]


def negotiate_raw(
    server: Server, item_id: str, profile: dict[str, Any] | None
) -> tuple[float, int, dict[str, str], bytes]:
    body: dict[str, Any] = {"UserId": server.user_id, "AutoOpenLiveStream": False}
    if profile is not None:
        body["DeviceProfile"] = profile
    started = time.monotonic()
    status, headers, payload = server.post_raw(f"/Items/{item_id}/PlaybackInfo", body=body)
    return time.monotonic() - started, status, headers, payload


# --------------------------------------------------------------------------------------------
# The batteries
# --------------------------------------------------------------------------------------------


def _listing_battery(server: Server, probe: Probe, items: dict[str, dict]) -> list[bool]:
    """OQ-3: what a listing answers for a source nothing successfully opened."""
    checks: list[bool] = []
    for label in ("unreadable", "empty"):
        source = listing_source(server, items[label]["Id"])
        probe.observe(f"listing, {label}", _shape(source))
        checks.append(
            not source.get("MediaStreams")
            and source.get("RunTimeTicks") is None
            and source.get("Bitrate") is None
            and source.get("Container") == "mkv"
            and source.get("SupportsDirectPlay") is True
            and source.get("SupportsDirectStream") is True
            and source.get("SupportsTranscoding") is True
            and not source.get("TranscodingUrl")
        )
    readable = listing_source(server, items["readable"]["Id"])
    probe.observe("listing, readable (control)", _shape(readable))
    checks.append(
        len(readable.get("MediaStreams") or []) == 2
        and readable.get("SupportsDirectPlay") is True
        and not readable.get("TranscodingUrl")
    )

    #: Every route this repository has that offers a media source, asserted to agree with each
    #: other rather than with a remembered shape: a listing that probed on one route and not on
    #: another would be the answer 012 section 3.2 is least able to specify around.
    item_id = items["unreadable"]["Id"]
    everywhere: list[str] = []
    query = server.get(
        "/Items",
        UserId=server.user_id,
        Ids=item_id,
        Recursive="true",
        Fields="MediaSources",
    )
    everywhere.append(_shape(((query.get("Items") or [{}])[0].get("MediaSources") or [{}])[0]))
    single = server.get(f"/Items/{item_id}", userId=server.user_id)
    everywhere.append(_shape((single.get("MediaSources") or [{}])[0]))
    latest = server.get(
        "/Items/Latest", userId=server.user_id, Limit=60, Fields="MediaSources", IsPlayed="false"
    )
    rows = [r for r in latest if r.get("Id") == item_id]
    if rows:
        everywhere.append(_shape((rows[0].get("MediaSources") or [{}])[0]))
    probe.observe("the same source on every listing route", f"{len(set(everywhere))} distinct")
    checks.append(len(set(everywhere)) == 1)
    return checks


def _negotiation_battery(server: Server, probe: Probe, items: dict[str, dict]) -> list[bool]:
    """OQ-2: what a negotiation answers when the on-demand probe cannot succeed."""
    checks: list[bool] = []
    for label in ("unreadable", "empty"):
        seconds, status, _, payload = negotiate_raw(server, items[label]["Id"], VIDEO_PROFILE)
        source = (json.loads(payload)["MediaSources"] or [{}])[0]
        probe.observe(f"negotiation, {label}", f"{seconds:.2f}s {status}: {_shape(source)}")
        checks.append(
            status == 200
            and not source.get("MediaStreams")
            and source.get("SupportsDirectPlay") is False
            and source.get("SupportsDirectStream") is False
            and source.get("SupportsTranscoding") is True
            and bool(source.get("TranscodingUrl"))
        )

    #: The address it hands out, followed. A capability with an address is only half of section
    #: 5's AC-2; the other half is whether the address answers.
    source = (
        json.loads(negotiate_raw(server, items["unreadable"]["Id"], VIDEO_PROFILE)[3])[
            "MediaSources"
        ]
        or [{}]
    )[0]
    url = source.get("TranscodingUrl") or ""
    status, headers, body = server.get_streaming(url, 2000)
    text = body.decode("utf-8", "replace")
    entry = next((line for line in text.splitlines() if line and not line.startswith("#")), "")
    probe.observe("its address, master playlist", f"{status} {headers.get('Content-Type')}")
    probe.observe("the line it names", entry[:60] or "none")
    prefix = url.split("?")[0].rsplit("/", 1)[0]
    status, headers, body = (
        server.get_streaming(f"{prefix}/{entry}", 400) if entry else (0, {}, b"")
    )
    probe.observe(
        "following that line",
        f"{status} {headers.get('Content-Type')} {body[:60]!r}",
    )
    checks.append(entry.startswith("live.m3u8") and status == 500)

    #: The audio item is the other half of section 2.2's "one rule, two faces", and it is the
    #: half neither client trace measured.
    probe.observe(
        "listing, audio with no audio stream",
        _shape(listing_source(server, items["broken_track"]["Id"])),
    )
    seconds, status, headers, payload = negotiate_raw(
        server, items["broken_track"]["Id"], AUDIO_PROFILE
    )
    probe.observe(
        "negotiation, audio with no audio stream",
        f"{seconds:.2f}s {status} {headers.get('Content-Type')} {payload[:60]!r}",
    )
    checks.append(status == 400)
    seconds, status, headers, payload = negotiate_raw(server, items["broken_track"]["Id"], None)
    probe.observe(
        "the same audio item, no profile",
        f"{seconds:.2f}s {status}: {_shape((json.loads(payload)['MediaSources'] or [{}])[0])}",
    )
    checks.append(status == 200)
    seconds, status, headers, payload = negotiate_raw(server, items["track"]["Id"], AUDIO_PROFILE)
    probe.observe(
        "a readable audio item, same profile (control)",
        f"{seconds:.2f}s {status}: {_shape((json.loads(payload)['MediaSources'] or [{}])[0])}",
    )
    checks.append(status == 200)

    #: A file that went away after the scan: nothing re-reads it, because the stored streams are
    #: what the refresh trigger looks at and they are still there.
    vanished = items["vanishing"]
    Path(vanished["Path"]).unlink(missing_ok=True)
    seconds, status, _, payload = negotiate_raw(server, vanished["Id"], VIDEO_PROFILE)
    source = (json.loads(payload)["MediaSources"] or [{}])[0]
    probe.observe(
        "negotiation, file deleted after the scan", f"{seconds:.2f}s {status}: {_shape(source)}"
    )
    checks.append(
        status == 200
        and len(source.get("MediaStreams") or []) == 2
        and bool(source.get("TranscodingUrl"))
    )
    return checks


def _on_demand_battery(server: Server, probe: Probe, items: dict[str, dict]) -> list[bool]:
    """OQ-1 and OQ-9: the probe that runs inside the request, and whether it is kept."""
    checks: list[bool] = []
    latent = items["latent"]
    before = listing_source(server, latent["Id"])
    probe.observe("latent, listing before", _shape(before))
    checks.append(not before.get("MediaStreams"))

    #: The bytes change with nothing told about it. No scan, no refresh request: the next
    #: negotiation is the only thing that has ever read this file successfully.
    shutil.copyfile(items["readable"]["Path"], latent["Path"])

    seconds, status, _, payload = negotiate_raw(server, latent["Id"], VIDEO_PROFILE)
    source = (json.loads(payload)["MediaSources"] or [{}])[0]
    probe.observe("latent, first negotiation", f"{seconds:.2f}s {status}: {_shape(source)}")
    checks.append(
        status == 200
        and len(source.get("MediaStreams") or []) == 2
        and source.get("RunTimeTicks")
        and source.get("Bitrate")
        and bool(source.get("TranscodingUrl"))
    )
    first_wait = seconds

    after = listing_source(server, latent["Id"])
    probe.observe("latent, listing after", _shape(after))
    checks.append(
        len(after.get("MediaStreams") or []) == 2
        and after.get("RunTimeTicks") == source.get("RunTimeTicks")
        and after.get("Size") == source.get("Size")
    )

    seconds, status, _, payload = negotiate_raw(server, latent["Id"], VIDEO_PROFILE)
    probe.observe("latent, second negotiation", f"{seconds:.2f}s {status}")
    checks.append(status == 200 and seconds < first_wait)

    #: The unreadable one is the control for the cost: it can never be resolved, so it pays the
    #: on-demand probe on every single negotiation, for ever.
    repeats = [
        round(negotiate_raw(server, items["unreadable"]["Id"], VIDEO_PROFILE)[0], 2)
        for _ in range(3)
    ]
    control = [
        round(negotiate_raw(server, items["readable"]["Id"], VIDEO_PROFILE)[0], 2) for _ in range(3)
    ]
    probe.observe("what the client waits for, unresolvable", f"{repeats} s")
    probe.observe("what it waits for, already annotated", f"{control} s")
    checks.append(min(repeats) > max(control))
    return checks


# --------------------------------------------------------------------------------------------


def run(server: Server, args: argparse.Namespace) -> Probe:
    probe = Probe(
        script="probe_uninspected_source.py",
        question="what does a negotiation answer for a source nothing has successfully opened, "
        "what does a listing answer, and is what an on-demand probe learns kept?",
        document="specs/012-negotiation-inputs/spec.md",
        section="sections 3.2 and 3.4, OQ-1, OQ-2, OQ-3, OQ-9",
    )
    given = Path(args.fixture_root).expanduser().resolve()
    root = given / FIXTURE_DIR
    server_root = f"{args.server_root or given}/{FIXTURE_DIR}"
    if root.exists():
        raise ProbeError(
            f"{root} already exists, which should be impossible: the name carries a fresh "
            "identifier per run. Remove it, and any leftover "
            f"{PREFIX}-* libraries, before running again"
        )

    made = build_fixture(root)
    try:
        add_library(server, MOVIE_LIBRARY, "movies", f"{server_root}/movies")
        add_library(server, MUSIC_LIBRARY, "music", f"{server_root}/music")
        probe.observe("scan", f"{scan_and_wait(server)}s")

        by_path = items_by_path(server)
        items: dict[str, dict[str, Any]] = {}
        for label, path in made.items():
            row = by_path.get(f"{server_root}/{path.relative_to(root).as_posix()}")
            if row is None:
                raise ProbeError(
                    f"the scan produced no item for {label}: the server sees "
                    f"{sorted(by_path)[:3]}. Check that --server-root names the same directory "
                    "as --fixture-root"
                )
            items[label] = {"Id": row["Id"], "Path": str(path)}
        probe.observe("items the scan produced", f"{len(items)} of {len(made)}")

        truncated = listing_source(server, items["truncated"]["Id"])
        probe.observe("listing, truncated to 1 KiB", _shape(truncated))

        checks = _listing_battery(server, probe, items)
        checks += _negotiation_battery(server, probe, items)
        checks += _on_demand_battery(server, probe, items)
    finally:
        for name in (MOVIE_LIBRARY, MUSIC_LIBRARY):
            status, _, _ = server.delete_raw(
                "/Library/VirtualFolders", name=name, refreshLibrary="false"
            )
            probe.observe(f"cleanup, {name}", status)
        shutil.rmtree(root, ignore_errors=True)
        probe.observe("cleanup, fixture removed", not root.exists())

    probe.note(
        "The reference has no un-inspected source to describe while the file is readable: the "
        "scan that creates an item probes it, and a negotiation of an item whose first source "
        "carries no stream of its own kind probes it again, inside the request "
        "[source: Emby.Server.Implementations/Library/MediaSourceManager.cs:170-189 @ v10.11.11]. "
        "What it has is an un-inspectable one, and that is what every observation above measures."
    )

    if all(checks):
        probe.conclude(
            "the negotiation probes on demand and the listing does not. A source the probe "
            "cannot read still answers a decided set of flags and an address - and that address "
            "resolves to a live playlist that answers 500, because a source with no runtime is "
            "addressed as an infinite stream. A source whose bytes became valid is fully "
            "annotated inside the first negotiation that asks for it, and the annotation is "
            "kept: the next listing carries the streams, the runtime and the corrected size. An "
            "audio item with no audio stream refuses the whole body with 400 rather than "
            "answering anything, and a file deleted after the scan is answered as though it were "
            "still there",
            matches_documentation=None,
        )
    else:
        failed = [i for i, ok in enumerate(checks) if not ok]
        probe.conclude(f"checks {failed} did not hold - see observations", False)
    return probe


def _extra_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--fixture-root",
        required=True,
        help="A directory this machine may write into, which the target server reads as a media "
        "path. The probe creates one subdirectory under it and removes it again.",
    )
    parser.add_argument(
        "--server-root",
        help="Where --fixture-root appears inside the server, when the two differ - a container's "
        "bind mount, typically. Defaults to --fixture-root.",
    )


if __name__ == "__main__":
    raise SystemExit(
        main(
            run,
            __doc__.splitlines()[0],
            needs_writes=True,
            extra_arguments=_extra_arguments,
            with_args=True,
        )
    )
