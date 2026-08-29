#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Which parts of a PlaybackInfo negotiation are real: the annotation, the switches, the
policies, the ErrorCode - and how the two routes refuse?

specs/008 §3.2-§3.3 made four claims this probe measures (OQ-1, OQ-2, OQ-12, and the policy
paragraph):

- the capability flags are annotated **per request** - the body's Enable* switches move them -
  not per source;
- `EnableTranscoding: false` in the request body is honoured;
- a user's playback policy gates the decision ladder step by step;
- refusals arrive as an `ErrorCode` from a three-value vocabulary.

Three batteries were added at 008 T5, when the routes were implemented. The **refusal battery**
measures the two rows of §3.2's error table that had never been measured at all - an unknown item,
an invisible one, and a request with no token - plus the one shape that carries an `ErrorCode`.
The **capabilities battery** asks what "no `DeviceProfile`" means, which turns out not to be
"no profile". Both follow the rule the 008 task list states for per-route refusals: a shape a
document cites is a shape a script here reproduces, never a hand request somebody once made.

The negotiation itself is read-only: PlaybackInfo reserves nothing until a delivery request
follows, and none does here. The **policy and capabilities batteries need --allow-writes**, and
the policy one an administrator token: the only way to measure what a policy denial does is to
have a user whose policy denies it, so the probe creates `atrium-probe-tmp`, flips its policy,
negotiates as it, and deletes it again - including on failure. The capabilities battery writes
only to the probe's own session and restores it.

Usage:
    python3 tools/probe_playback_info.py http://your-jellyfin:8096 -u admin --allow-writes
"""

from __future__ import annotations

import json
import secrets

from _playback import base_profile, negotiate, pick_video_source
from _probe import Probe, ProbeError, Server, main

#: A well-formed identifier nothing owns. The refusal battery needs the *item* lookup to fail,
#: not the parse: a malformed id is the model binder's 400 and a different question.
#:
#: **Not all zeros**, which is the trap this constant exists to avoid. The all-zeros form is the
#: reference's `Guid.Empty` and never reaches a lookup at all - it is refused by a guard that
#: throws `[source: Emby.Server.Implementations/Library/LibraryManager.cs:1359-1362 @ v10.11.11]`
#: - so a battery written with it measures the guard and reports it as "unknown item".
NOTHING_OWNS_THIS = "a7c1f5e30b9d4a6c8e2f1b3d5a7c9e10"

#: The reference's empty GUID, measured on its own row because it is a *different* refusal.
EMPTY_GUID = "00000000000000000000000000000000"


def _flags(data: dict) -> str:
    source = data["MediaSources"][0]
    bits = ", ".join(
        f"{key[8:]}={source.get(key)}"
        for key in ("SupportsDirectPlay", "SupportsDirectStream", "SupportsTranscoding")
    )
    url = "url" if source.get("TranscodingUrl") else "no url"
    return f"{bits}, {url}, ErrorCode={data.get('ErrorCode')!r}"


def _shape(status: int, headers: dict, body: bytes) -> str:
    """A refusal as bytes rather than as a status code: the body is half of the contract."""
    kind = headers.get("Content-Type") or "no Content-Type"
    return f"{status}, {kind}, {len(body)} bytes: {body[:90]!r}"


def _policy_battery(server: Server, probe: Probe, source, reject_vcodec) -> list[bool]:
    """Negotiate as a user whose policy denies steps. Creates and deletes a throwaway user.

    The **invisible item** runs here too, last, and reuses the same throwaway account: an item is
    invisible to a user whose policy grants them no library, and manufacturing such a user is the
    one thing the refusal battery cannot do read-only. It is measured after the policy shapes
    because it takes the item away from the account the earlier ones negotiate on.
    """
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

        set_policy(EnableAllFolders=False, EnabledFolders=[])
        status, headers, body = as_user.post_raw(
            f"/Items/{source.item_id}/PlaybackInfo", body={"UserId": as_user.user_id}
        )
        probe.observe("invisible item, POST", _shape(status, headers, body))
        checks.append(status == 404)
        status, headers, body = as_user.get_raw(
            f"/Items/{source.item_id}/PlaybackInfo", userId=as_user.user_id
        )
        probe.observe("invisible item, GET", _shape(status, headers, body))
        checks.append(status == 404)
    finally:
        status, _, _ = server.delete_raw(f"/Users/{user_id}")
        probe.observe("throwaway user deleted", status)
    return checks


def _refusal_battery(server: Server, probe: Probe, item_id: str) -> list[bool]:
    """Every refusal the two negotiation routes can produce, as bytes rather than as statuses.

    Read-only, and the reason it exists: §3.2's error table cited nothing for its first two rows.
    The `ErrorCode` case is here too, because the reference has exactly one assignment site for it
    and the only way a v1 request reaches that site is by naming a media source the item does not
    have - a profile that can play nothing is a *flags* refusal (probe_playback_refusal.py).
    """
    checks: list[bool] = []
    anonymous = Server(server.base, timeout=server.timeout)

    status, headers, body = anonymous.post_raw(f"/Items/{item_id}/PlaybackInfo", body={})
    probe.observe("no token, POST", _shape(status, headers, body))
    checks.append(status == 401 and not body)

    status, headers, body = anonymous.get_raw(f"/Items/{item_id}/PlaybackInfo")
    probe.observe("no token, GET", _shape(status, headers, body))
    checks.append(status == 401 and not body)

    status, headers, body = server.post_raw(
        f"/Items/{NOTHING_OWNS_THIS}/PlaybackInfo", body={"UserId": server.user_id}
    )
    probe.observe("unknown item, POST", _shape(status, headers, body))
    checks.append(status == 404)

    status, headers, body = server.get_raw(
        f"/Items/{NOTHING_OWNS_THIS}/PlaybackInfo", userId=server.user_id
    )
    probe.observe("unknown item, GET", _shape(status, headers, body))
    checks.append(status == 404)

    status, headers, body = server.post_raw(
        f"/Items/{EMPTY_GUID}/PlaybackInfo", body={"UserId": server.user_id}
    )
    probe.observe("the all-zeros id, POST", _shape(status, headers, body))
    checks.append(status == 400)

    status, headers, body = server.post_raw(
        f"/Items/{item_id}/PlaybackInfo", body={"UserId": server.user_id}
    )
    document = json.loads(body)
    probe.observe("a negotiation's top-level properties", list(document))
    checks.append(status == 200 and "ErrorCode" not in document and "PlaySessionId" in document)

    status, headers, body = server.post_raw(
        f"/Items/{item_id}/PlaybackInfo",
        body={"UserId": server.user_id, "MediaSourceId": NOTHING_OWNS_THIS},
    )
    probe.observe("MediaSourceId naming no part of the item", _shape(status, headers, body))
    document = json.loads(body)
    checks.append(
        status == 200
        and document.get("MediaSources") == []
        and document.get("ErrorCode") == "NoCompatibleStream"
        and "PlaySessionId" not in document
    )
    return checks


def _capabilities_battery(server: Server, probe: Probe, source, reject_container) -> list[bool]:
    """What does a POST with **no** `DeviceProfile` negotiate against?

    Writes to the probe's own session - `POST /Sessions/Capabilities/Full` replaces whatever that
    session held - and restores a profile-less document afterwards, including on failure.
    """
    checks: list[bool] = []

    def capabilities(profile) -> None:
        body = {
            "PlayableMediaTypes": ["Video", "Audio"],
            "SupportedCommands": [],
            "SupportsMediaControl": False,
            "SupportsPersistentIdentifier": False,
        }
        if profile is not None:
            body["DeviceProfile"] = profile
        status, _, payload = server.post_raw("/Sessions/Capabilities/Full", body=body)
        if status != 204:
            raise ProbeError(
                f"POST /Sessions/Capabilities/Full answered {status}: {payload[:120]!r}"
            )

    try:
        capabilities(reject_container)
        status, data = negotiate(server, source.item_id, None)
        probe.observe("no profile, device capabilities carry one", f"{status}: {_flags(data)}")
        one = data["MediaSources"][0]
        checks.append(
            status == 200
            and one.get("SupportsDirectPlay") is False
            and bool(one.get("TranscodingUrl"))
        )

        got = server.get(f"/Items/{source.item_id}/PlaybackInfo", userId=server.user_id)
        probe.observe("GET variant, same stored profile", _flags(got))
        checks.append(got["MediaSources"][0].get("SupportsDirectPlay") is True)
    finally:
        capabilities(None)
        status, data = negotiate(server, source.item_id, None)
        probe.observe("no profile, capabilities cleared", f"{status}: {_flags(data)}")
        checks.append(data["MediaSources"][0].get("SupportsDirectPlay") is True)
    return checks


def run(server: Server, args) -> Probe:
    probe = Probe(
        script="probe_playback_info.py",
        question="are the flags per request, do the switches and policies bite, when does an "
        "ErrorCode appear, and how do the two routes refuse?",
        document="specs/008-playback-negotiation-and-delivery/spec.md",
        section="sections 3.2 and 3.3",
        expectation=(
            "annotation is per request (EnableDirectPlay=false clears the flag); "
            "EnableTranscoding=false in the body changes nothing; a policy denial changes "
            "nothing at negotiation unless every step is denied, and even then it is flags, "
            "not an ErrorCode; the only ErrorCode the reference can produce is "
            "NoCompatibleStream on an empty source list; an unknown or invisible item is 404 "
            "and a request with no token is 401; and a POST carrying no DeviceProfile "
            "negotiates against nothing"
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
    #: Rejects only the container, so an answer attributable to it is attributable to nothing
    #: else - which is what makes the capabilities battery's "no profile" answer readable.
    reject_container = base_profile(
        [
            {
                "Container": source.other_container(),
                "Type": "Video",
                "VideoCodec": source.video_codec,
                "AudioCodec": ",".join(source.audio_codecs),
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

    checks.extend(_refusal_battery(server, probe, source.item_id))

    if args.allow_writes:
        checks.extend(_policy_battery(server, probe, source, reject_vcodec))
        checks.extend(_capabilities_battery(server, probe, source, reject_container))
    else:
        probe.note(
            "policy and capabilities batteries skipped: re-run with --allow-writes and an "
            "administrator to measure what a policy denial does to this negotiation, and what "
            "a stored device profile does to a request that carries none."
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
            "flags), and no ErrorCode anywhere a source exists. The refusals: an empty 401 for "
            "a request with no token, problem details for an unknown item and for an invisible "
            "one, and the ErrorCode only where the source list is empty - which also drops the "
            "PlaySessionId. And a POST carrying no DeviceProfile is not a POST with no profile: "
            "the device's stored capabilities supply one, and only the GET is profile-less",
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
        help="Also run the policy and capabilities batteries. The first creates a throwaway user "
        "(admin required), flips its policy, and deletes it again - including on failure; the "
        "second replaces the probe's own session capabilities and restores them. Without this "
        "flag the probe is read-only and both are skipped.",
    )


if __name__ == "__main__":
    raise SystemExit(
        main(run, __doc__.splitlines()[0], extra_arguments=_extra_arguments, with_args=True)
    )
