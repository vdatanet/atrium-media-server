#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Which parts of a PlaybackInfo negotiation are real: the annotation, the switches, the
policies, the ErrorCode?

specs/008 §3.2-§3.3 made four claims this probe measures (OQ-1, OQ-2, OQ-12, and the policy
paragraph):

- the capability flags are annotated **per request** - the body's Enable* switches move them -
  not per source;
- `EnableTranscoding: false` in the request body is honoured;
- a user's playback policy gates the decision ladder step by step;
- refusals arrive as an `ErrorCode` from a three-value vocabulary.

The negotiation itself is read-only: PlaybackInfo reserves nothing until a delivery request
follows, and none does here. The **policy battery needs --allow-writes and an administrator
token**: the only way to measure what a policy denial does is to have a user whose policy denies
it, so the probe creates `atrium-probe-tmp`, flips its policy, negotiates as it, and deletes it
again - including on failure.

Usage:
    python3 tools/probe_playback_info.py http://your-jellyfin:8096 -u admin --allow-writes
"""

from __future__ import annotations

import secrets

from _playback import base_profile, negotiate, pick_video_source
from _probe import Probe, ProbeError, Server, main


def _flags(data: dict) -> str:
    source = data["MediaSources"][0]
    bits = ", ".join(
        f"{key[8:]}={source.get(key)}"
        for key in ("SupportsDirectPlay", "SupportsDirectStream", "SupportsTranscoding")
    )
    url = "url" if source.get("TranscodingUrl") else "no url"
    return f"{bits}, {url}, ErrorCode={data.get('ErrorCode')!r}"


def _policy_battery(server: Server, probe: Probe, source, reject_vcodec) -> list[bool]:
    """Negotiate as a user whose policy denies steps. Creates and deletes a throwaway user."""
    me = server.get("/Users/Me")
    if not me["Policy"]["IsAdministrator"]:
        raise ProbeError(
            "the policy battery needs an administrator: only an admin can create the throwaway "
            "user whose policy the probe flips. Re-run with an admin account, or without "
            "--allow-writes to skip this battery"
        )
    password = secrets.token_hex(12)
    made = server.post("/Users/New", body={"Name": "atrium-probe-tmp", "Password": password})
    user_id = made["Id"]
    checks: list[bool] = []
    try:

        def set_policy(**changes) -> None:
            policy = server.get(f"/Users/{user_id}")["Policy"]
            policy.update(changes)
            status, _, body = server.post_raw(f"/Users/{user_id}/Policy", body=policy)
            if status not in (200, 204):
                raise ProbeError(f"POST /Users/{{id}}/Policy answered {status}: {body[:120]!r}")

        as_user = Server(server.base, timeout=server.timeout)
        as_user.connect("atrium-probe-tmp", password, None)

        set_policy(EnableMediaPlayback=False)
        status, data = negotiate(as_user, source.item_id, reject_vcodec)
        probe.observe("EnableMediaPlayback=false", f"{status}: {_flags(data)}")
        checks.append(
            status == 200
            and data.get("ErrorCode") is None
            and bool(data["MediaSources"][0].get("TranscodingUrl"))
        )

        set_policy(
            EnableMediaPlayback=True,
            EnableVideoPlaybackTranscoding=False,
            EnableAudioPlaybackTranscoding=False,
            EnablePlaybackRemuxing=True,
        )
        status, data = negotiate(as_user, source.item_id, reject_vcodec)
        probe.observe("transcoding denied, remux allowed", f"{status}: {_flags(data)}")
        checks.append(status == 200 and bool(data["MediaSources"][0].get("TranscodingUrl")))

        set_policy(EnablePlaybackRemuxing=False)
        status, data = negotiate(as_user, source.item_id, reject_vcodec)
        probe.observe("all three steps denied", f"{status}: {_flags(data)}")
        one = data["MediaSources"][0]
        checks.append(
            status == 200
            and one.get("SupportsTranscoding") is False
            and not one.get("TranscodingUrl")
            and data.get("ErrorCode") is None
        )
    finally:
        status, _, _ = server.delete_raw(f"/Users/{user_id}")
        probe.observe("throwaway user deleted", status)
    return checks


def run(server: Server, args) -> Probe:
    probe = Probe(
        script="probe_playback_info.py",
        question="are the flags per request, do the switches and policies bite, and when "
        "does an ErrorCode appear?",
        document="specs/008-playback-negotiation-and-delivery/spec.md",
        section="sections 3.2 and 3.3",
        expectation=(
            "annotation is per request (EnableDirectPlay=false clears the flag); "
            "EnableTranscoding=false in the body changes nothing; a policy denial changes "
            "nothing at negotiation unless every step is denied, and even then it is flags, "
            "not an ErrorCode; the only ErrorCode the reference can produce is "
            "NoCompatibleStream on an empty source list"
        ),
    )

    source = pick_video_source(server)
    probe.observe(
        "measured source",
        f"{source.container}, video {source.video_codec}, audio {'/'.join(source.audio_codecs)}",
    )
    accepts_all = base_profile(
        [
            {
                "Container": source.container,
                "Type": "Video",
                "VideoCodec": source.video_codec,
                "AudioCodec": ",".join(source.audio_codecs),
            }
        ]
    )
    reject_vcodec = base_profile(
        [
            {
                "Container": source.other_container(),
                "Type": "Video",
                "VideoCodec": source.other_video_codec(),
                "AudioCodec": "aac",
            }
        ]
    )
    checks: list[bool] = []

    status, data = negotiate(server, source.item_id, None)
    probe.observe("no profile", f"{status}: {_flags(data)}")
    one = data["MediaSources"][0]
    checks.append(status == 200 and one.get("SupportsDirectPlay") is True)

    got = server.get(f"/Items/{source.item_id}/PlaybackInfo", userId=server.user_id)
    one = got["MediaSources"][0]
    probe.observe("GET variant", _flags(got))
    checks.append(
        one.get("SupportsDirectPlay") is True
        and not one.get("TranscodingUrl")
        and bool(got.get("PlaySessionId"))
    )

    status, data = negotiate(server, source.item_id, accepts_all)
    probe.observe("profile accepting the source", f"{status}: {_flags(data)}")
    checks.append(data["MediaSources"][0].get("SupportsDirectPlay") is True)

    status, data = negotiate(server, source.item_id, accepts_all, EnableDirectPlay=False)
    probe.observe("same profile, EnableDirectPlay=false", f"{status}: {_flags(data)}")
    one = data["MediaSources"][0]
    checks.append(one.get("SupportsDirectPlay") is False and bool(one.get("TranscodingUrl")))

    status, data = negotiate(server, source.item_id, reject_vcodec, EnableTranscoding=False)
    probe.observe("codec-rejecting profile, EnableTranscoding=false", f"{status}: {_flags(data)}")
    one = data["MediaSources"][0]
    checks.append(
        one.get("SupportsTranscoding") is True
        and bool(one.get("TranscodingUrl"))
        and data.get("ErrorCode") is None
    )

    if args.allow_writes:
        checks.extend(_policy_battery(server, probe, source, reject_vcodec))
    else:
        probe.note(
            "policy battery skipped: re-run with --allow-writes and an administrator to "
            "measure what a policy denial does to this negotiation."
        )

    probe.note(
        "ErrorCode: the response enum is NotAllowed / NoCompatibleStream / RateLimitExceeded "
        "[spec: PlaybackInfoResponse], but only one assignment site exists at 10.11.11 - "
        "NoCompatibleStream when the media source list is empty [source: "
        "Jellyfin.Api/Helpers/MediaInfoHelper.cs:123 @ v10.11.11]. NotAllowed and "
        "RateLimitExceeded are dead vocabulary. EnableMediaPlayback=false is consumed only by "
        "the item DTO's PlayAccess and the remote-control Play command [source: "
        "MediaBrowser.Controller/Entities/BaseItem.cs:1057, "
        "Emby.Server.Implementations/Session/SessionManager.cs:1321 @ v10.11.11]."
    )

    if all(checks):
        probe.conclude(
            "as now documented: per-request annotation, an ignored EnableTranscoding switch, "
            "policy denials that move nothing until every step is denied (and then only the "
            "flags), and no ErrorCode anywhere a source exists",
            matches_documentation=True,
        )
    else:
        failed = [i for i, ok in enumerate(checks) if not ok]
        probe.conclude(f"checks {failed} did not hold - see observations", False)
    return probe


def _extra_arguments(parser) -> None:
    parser.add_argument(
        "--allow-writes",
        action="store_true",
        help="Also run the policy battery, which creates a throwaway user (admin required), "
        "flips its policy, and deletes it again - including on failure. Without this flag the "
        "probe is read-only and the battery is skipped.",
    )


if __name__ == "__main__":
    raise SystemExit(
        main(run, __doc__.splitlines()[0], extra_arguments=_extra_arguments, with_args=True)
    )
