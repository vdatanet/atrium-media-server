#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""How does a direct-play delivery route answer each shape of Range header - and what does
`static=true` serve when the URL names the wrong container?

specs/008 §3.5's table and §6's range matrix: no range, a prefix, a mid-file slice, a suffix, a
reversed range, a multi-range, and one byte past the end - the shapes where range
implementations actually break. Measured against `/Videos/{itemId}/stream?static=true`, the
route whose body is the original file. Plus the static-mismatch case: a container-suffixed
static URL that does not match the source answers the untouched original bytes behind the
path's Content-Type label - no error, no remux.

Read-only, and it never downloads the film: every request reads at most 64 bytes of the answer
and closes - the status, `Content-Range` and `Content-Length` are the whole question.

Usage:
    python3 tools/probe_range_matrix.py http://your-jellyfin:8096 -u username
"""

from __future__ import annotations

from _playback import pick_video_source
from _probe import Probe, Server, main


def run(server: Server) -> Probe:
    probe = Probe(
        script="probe_range_matrix.py",
        question="what does static delivery answer to each shape of Range header?",
        document="specs/008-playback-negotiation-and-delivery/spec.md",
        section="section 3.5, the range table",
        expectation=(
            "no Range: 200 full body with Accept-Ranges: bytes and Content-Length equal to the "
            "file size; bytes=100-199: 206 with the correct Content-Range and exactly 100 "
            "bytes; a suffix range: 206 with the last bytes; multi-range and reversed: the "
            "full body as 200, never split, never refused; one byte past the end: 416 with "
            "Content-Range: bytes */total and Content-Length 0; and static=true through a "
            "mismatched container suffix serves the identical original bytes with the path's "
            "Content-Type label"
        ),
    )

    source = pick_video_source(server)
    size = source.source.get("Size")
    probe.observe("measured source", f"{source.container}, {size} bytes")
    path = f"/Videos/{source.item_id}/stream?static=true&api_key={server.token}"

    def ask(range_header: str | None) -> tuple[int, str | None, str | None]:
        extra = {"Range": range_header} if range_header else None
        status, headers, _ = server.get_streaming(path, max_bytes=64, extra_headers=extra)
        return status, headers.get("Content-Range"), headers.get("Content-Length")

    checks: list[bool] = []

    status, content_range, length = ask(None)
    probe.observe("no Range", f"{status}, Content-Length {length}")
    checks.append(status == 200 and length == str(size))

    status, content_range, length = ask("bytes=100-199")
    probe.observe("bytes=100-199", f"{status}, {content_range}, Content-Length {length}")
    checks.append(status == 206 and content_range == f"bytes 100-199/{size}" and length == "100")

    status, content_range, length = ask("bytes=-100")
    probe.observe("bytes=-100 (suffix)", f"{status}, {content_range}, Content-Length {length}")
    checks.append(
        status == 206
        and content_range == f"bytes {size - 100}-{size - 1}/{size}"
        and length == "100"
    )

    status, content_range, length = ask("bytes=0-49,100-149")
    probe.observe("bytes=0-49,100-149 (multi)", f"{status}, Content-Length {length}")
    checks.append(status == 200 and length == str(size))

    status, content_range, length = ask("bytes=200-100")
    probe.observe("bytes=200-100 (reversed)", f"{status}, Content-Length {length}")
    checks.append(status == 200 and length == str(size))

    status, content_range, length = ask(f"bytes={size}-")
    probe.observe("one byte past the end", f"{status}, {content_range}, Content-Length {length}")
    checks.append(status == 416 and content_range == f"bytes */{size}" and length == "0")

    _, _, true_head = server.get_streaming(
        path, max_bytes=64, extra_headers={"Range": "bytes=0-63"}
    )
    wrong = source.other_container()
    mismatch = f"/Videos/{source.item_id}/stream.{wrong}?static=true&api_key={server.token}"
    status, headers, head = server.get_streaming(
        mismatch, max_bytes=64, extra_headers={"Range": "bytes=0-63"}
    )
    probe.observe(
        f"stream.{wrong}?static=true on a {source.container} source",
        f"{status}, Content-Type {headers.get('Content-Type')}, original bytes: "
        f"{head == true_head}",
    )
    checks.append(status in (200, 206) and head == true_head)

    if all(checks):
        probe.conclude(
            "as documented: correct 206 slices, full-body 200 for the shapes it will not "
            "split or refuse, the RFC's 416 for the unsatisfiable one, and untouched "
            "original bytes behind the path's label on a mismatched static suffix",
            matches_documentation=True,
        )
    else:
        failed = [i for i, ok in enumerate(checks) if not ok]
        probe.conclude(f"checks {failed} did not hold - see observations", False)
    return probe


if __name__ == "__main__":
    raise SystemExit(main(run, __doc__.splitlines()[0]))
