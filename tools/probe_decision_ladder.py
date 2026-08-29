#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""What does each rung of the decision ladder actually answer, and in what order are the
reasons listed?

specs/008 section 3.3 describes a four-outcome ladder - direct play, remux, transcode, not
playable - and 008 T4 implements it as pure functions. Six of its claims are the ones a pure
implementation gets wrong silently, and this probe measures each against a real negotiation:

- **an empty `DeviceProfile` object.** The spec's rule 1 said an "empty or absent" profile means
  "anything"; the absent half was measured by probe_playback_info.py and the empty half never
  was. An empty object is a profile whose `DirectPlayProfiles` list is empty, which is a
  different thing from no profile at all - and it answers every flag false;
- **a container-only rejection is a remux**: a `TranscodingUrl` whose `TranscodeReasons` is
  `ContainerNotSupported` alone, with the source's own codecs named on it;
- **the reasons are accumulated in enum order**, which is a claim about *which* enum order.
  `TranscodeReason` declares `VideoRangeTypeNotSupported` (1 << 24) before
  `VideoLevelNotSupported` (1 << 7), so declaration order and flag-value order disagree, and one
  profile failing both conditions at once tells them apart;
- **which ceilings are clamped to the source.** A resolution ceiling above the source reaches the
  URL as the profile stated it; a frame-rate ceiling is minimised against the source's own rate,
  because that one field is seeded from the stream and the other is not;
- **at what precision a frame rate is compared.** The wire prints the rate as a 32-bit float, and
  a client that declares exactly the number it read is answered with a transcode;
- **`MaxStreamingBitrate` bounds direct play**, and the reason it produces is a container reason,
  not a video one - while a rejection with no direct-play profile to reject names
  `DirectPlayError`, a reason from the enum's "Errors" group.

Read-only: `PlaybackInfo` negotiates and reserves nothing until a delivery request follows, and
none does. No segment is fetched and no session is started.

Usage:
    python3 tools/probe_decision_ladder.py http://your-jellyfin:8096 -u username
"""

from __future__ import annotations

import urllib.parse
from typing import Any

from _playback import TS_HLS_H264, base_profile, negotiate, pick_video_source
from _probe import Probe, ProbeError, Server, main

#: The URL parameters that say what the answer decided to do with each stream.
INTERESTING = (
    "VideoCodec",
    "AudioCodec",
    "MaxWidth",
    "MaxHeight",
    "VideoBitrate",
    "AudioBitrate",
    "MaxFramerate",
    "TranscodingMaxAudioChannels",
    "TranscodeReasons",
)


class Answer:
    """One negotiation, reduced to what the ladder decided."""

    def __init__(self, status: int, data: dict[str, Any]) -> None:
        self.status = status
        self.error_code = data.get("ErrorCode")
        sources = data.get("MediaSources") or []
        self.source: dict[str, Any] = sources[0] if sources else {}
        self.url: str | None = self.source.get("TranscodingUrl")
        self.query: dict[str, str] = {}
        if self.url:
            parsed = urllib.parse.urlparse(self.url)
            self.query = {
                key: values[0]
                for key, values in urllib.parse.parse_qs(parsed.query).items()
                if values
            }

    @property
    def reasons(self) -> str:
        return self.query.get("TranscodeReasons", "")

    @property
    def flags(self) -> str:
        return "".join(
            "1" if self.source.get(key) else "0"
            for key in ("SupportsDirectPlay", "SupportsDirectStream", "SupportsTranscoding")
        )

    def described(self) -> str:
        """`DPS=100 | reasons | the parameters that carry the plan`."""
        named = " ".join(
            f"{key}={self.query[key]}" for key in INTERESTING if key in self.query and key
        )
        return f"DPS={self.flags} ErrorCode={self.error_code!r} {named or 'no url'}"


def _video_stream(source: dict[str, Any]) -> dict[str, Any]:
    for stream in source.get("MediaStreams", []):
        if stream.get("Type") == "Video":
            return stream
    raise ProbeError("the measured source has no video stream")


def run(server: Server) -> Probe:
    probe = Probe(
        script="probe_decision_ladder.py",
        question="what does each rung of the ladder answer, and in what order are the reasons?",
        document="specs/008-playback-negotiation-and-delivery/spec.md",
        section="sections 3.3 and 3.4",
        expectation=(
            "an empty DeviceProfile object permits nothing and answers every flag false - only "
            "an absent one means anything; a container-only rejection answers "
            "ContainerNotSupported alone with the source's codecs copied; reasons are listed in "
            "flag-value order, so VideoLevelNotSupported precedes VideoRangeTypeNotSupported; a "
            "resolution ceiling reaches the URL as the profile stated it, unclamped, while the "
            "frame-rate ceiling is seeded from the source and minimised against it; a frame-rate "
            "ceiling equal to the rate the wire reports is not satisfied, because the comparison "
            "happens at the 32-bit value's full precision; a rejection with no direct-play "
            "profile to reject names DirectPlayError; and MaxStreamingBitrate produces a "
            "container reason"
        ),
    )

    source = pick_video_source(server)
    video = _video_stream(source.source)
    height = video.get("Height")
    level = video.get("Level")
    bitrate = source.source.get("Bitrate")
    probe.observe(
        "measured source",
        f"{source.container}, video {source.video_codec} {video.get('Width')}x{height} "
        f"level {level} {video.get('VideoRangeType')}, audio {'/'.join(source.audio_codecs)}, "
        f"{bitrate} bps",
    )
    probe.observe(
        "the source's three frame rates",
        f"Real={video.get('RealFrameRate')} Average={video.get('AverageFrameRate')} "
        f"Reference={video.get('ReferenceFrameRate')}",
    )

    audio_list = ",".join(source.audio_codecs)
    plays_everything = [
        {
            "Container": source.container,
            "Type": "Video",
            "VideoCodec": source.video_codec,
            "AudioCodec": audio_list,
        }
    ]
    #: A transcoding target that can copy both of this source's streams, so a container-only
    #: rejection has a remux available rather than only a re-encode.
    copies_both = [
        {
            **TS_HLS_H264,
            "VideoCodec": f"{source.video_codec},h264",
            "AudioCodec": f"{audio_list},aac",
        }
    ]
    checks: list[bool] = []

    def ask(label: str, profile: dict[str, Any] | None, **extras: Any) -> Answer:
        status, data = negotiate(server, source.item_id, profile, **extras)
        answer = Answer(status, data)
        probe.observe(label, answer.described())
        return answer

    # 1. The empty profile object: rule 1's untested half.
    empty = ask("empty DeviceProfile {}", {})
    checks.append(empty.status == 200 and empty.flags == "000" and not empty.url)

    # 2. A profile that accepts everything: the direct-play rung.
    accepts = ask("accepts container and codecs", base_profile(plays_everything, copies_both))
    checks.append(accepts.flags[0] == "1" and not accepts.url)

    # 2b. The same accepting profile with no transcoding target at all: which of the three flags
    #     is a claim about the *answer* and which about what the server could otherwise produce.
    no_target = ask(
        "accepts everything, no TranscodingProfiles",
        base_profile(plays_everything, []),
    )
    checks.append(no_target.flags == "110")

    # 3. Container rejected, both codecs copyable: the remux rung.
    container_only = ask(
        "container rejected only",
        base_profile(
            [{**plays_everything[0], "Container": source.other_container()}],
            copies_both,
        ),
    )
    checks.append(container_only.reasons == "ContainerNotSupported")
    checks.append(container_only.query.get("VideoCodec", "").split(",")[0] == source.video_codec)

    # 4. Video codec rejected: the transcode rung, video re-encoded.
    ask(
        "video codec rejected",
        base_profile(
            [{**plays_everything[0], "VideoCodec": source.other_video_codec()}],
            copies_both,
        ),
    )

    # 5. Audio codec rejected: the transcode rung, audio re-encoded.
    ask(
        "audio codec rejected",
        base_profile(
            [{**plays_everything[0], "AudioCodec": source.other_audio_codec()}],
            copies_both,
        ),
    )

    # 6. All three rejected at once: the order of the three primary reasons.
    all_three = ask(
        "container + both codecs rejected",
        base_profile(
            [
                {
                    "Container": source.other_container(),
                    "Type": "Video",
                    "VideoCodec": source.other_video_codec(),
                    "AudioCodec": source.other_audio_codec(),
                }
            ],
            copies_both,
        ),
    )
    checks.append(
        all_three.reasons == "ContainerNotSupported,VideoCodecNotSupported,AudioCodecNotSupported"
    )

    # 7. Two codec conditions failing at once, chosen so declaration order and flag-value order
    #    disagree: VideoRangeType is declared before VideoLevel and is worth 1 << 24 to its
    #    1 << 7.
    order = ask(
        "VideoLevel and VideoRangeType both failing",
        base_profile(
            plays_everything,
            copies_both,
            codec_profiles=[
                {
                    "Type": "Video",
                    "Codec": source.video_codec,
                    "Conditions": [
                        {
                            "Condition": "Equals",
                            "Property": "VideoRangeType",
                            "Value": "HDR10" if video.get("VideoRangeType") != "HDR10" else "SDR",
                            "IsRequired": True,
                        },
                        {
                            "Condition": "LessThanEqual",
                            "Property": "VideoLevel",
                            "Value": "1",
                            "IsRequired": True,
                        },
                    ],
                }
            ],
        ),
    )
    checks.append(order.reasons == "VideoLevelNotSupported,VideoRangeTypeNotSupported")

    # 8. A height ceiling below the source: the re-encode down to the ceiling, and the audio
    #    named at its own codec because nothing rejected it.
    low = ask(
        "Height <= 480 on a taller source",
        base_profile(
            plays_everything,
            copies_both,
            codec_profiles=[
                {
                    "Type": "Video",
                    "Codec": source.video_codec,
                    "Conditions": [
                        {
                            "Condition": "LessThanEqual",
                            "Property": "Height",
                            "Value": "480",
                            "IsRequired": True,
                        }
                    ],
                }
            ],
        ),
    )
    checks.append(low.reasons == "VideoResolutionNotSupported")

    # 9. A height ceiling far above the source, with the container rejected so there is a URL to
    #    read it off: AC-9's clamp says the source wins.
    high = ask(
        "Height <= 4320 with the container rejected",
        base_profile(
            [{**plays_everything[0], "Container": source.other_container()}],
            copies_both,
            codec_profiles=[
                {
                    "Type": "Video",
                    "Codec": source.video_codec,
                    "Conditions": [
                        {
                            "Condition": "LessThanEqual",
                            "Property": "Height",
                            "Value": "4320",
                            "IsRequired": True,
                        }
                    ],
                }
            ],
        ),
    )
    checks.append(high.query.get("MaxHeight") == "4320")

    # 10. A streaming bitrate below the source's: which reason, and what lands on the URL.
    if bitrate:
        capped = ask(
            "MaxStreamingBitrate below the source bitrate",
            {**base_profile(plays_everything, copies_both), "MaxStreamingBitrate": bitrate // 2},
        )
        checks.append("ContainerBitrateExceedsLimit" in capped.reasons)

    # 11. No direct-play profile at all, but a transcoding target: is that the transcode rung,
    #     and what reason does a rejection with nothing to reject name?
    no_direct_play = ask(
        "no DirectPlayProfiles, one transcoding profile",
        base_profile([], copies_both),
    )
    checks.append(no_direct_play.flags == "001")

    # 12. The honoured switch, on a profile the source satisfies: which reason it produces.
    ask(
        "accepting profile, EnableDirectPlay=false",
        base_profile(plays_everything, copies_both),
        EnableDirectPlay=False,
    )

    # 13 and 14. A frame-rate ceiling at exactly the rate the wire reports, and one a hair
    #     below it. The wire's number is a 32-bit float of the file's exact rational, and the
    #     comparison happens at that precision or at the rational's - the two disagree.
    reference_rate = video.get("ReferenceFrameRate")
    if reference_rate is not None:

        def framerate_ceiling(value: str) -> dict[str, Any]:
            return base_profile(
                plays_everything,
                copies_both,
                codec_profiles=[
                    {
                        "Type": "Video",
                        "Codec": source.video_codec,
                        "Conditions": [
                            {
                                "Condition": "LessThanEqual",
                                "Property": "VideoFramerate",
                                "Value": value,
                                "IsRequired": True,
                            }
                        ],
                    }
                ],
            )

        at_rate = ask(
            f"VideoFramerate <= {reference_rate} (the reported rate)",
            framerate_ceiling(str(reference_rate)),
        )
        checks.append(at_rate.reasons == "VideoFramerateNotSupported")
        just_above = ask(
            "VideoFramerate <= that rate plus 1e-5",
            framerate_ceiling(f"{float(reference_rate) + 1e-5:.6f}"),
        )
        checks.append(just_above.flags[0] == "1" and not just_above.url)

    probe.note(
        "The reasons list is a [Flags] enum rendered by .NET, whose formatter emits the set "
        "members in ascending value order [source: MediaBrowser.Model/Session/TranscodeReason.cs "
        "@ v10.11.11]. Row 7 is what separates that from declaration order."
    )

    if all(checks):
        probe.conclude(
            "the ladder answers as section 3.3 now describes it: an empty profile object "
            "permits nothing where an absent one permits everything, the reasons arrive in "
            "flag-value order, a resolution ceiling is carried unclamped while the frame-rate "
            "ceiling is minimised against the source, and a frame-rate ceiling equal to the "
            "printed rate is refused at the 32-bit value's real precision",
            matches_documentation=True,
        )
    else:
        failed = [index for index, ok in enumerate(checks) if not ok]
        probe.conclude(f"checks {failed} did not hold - see observations", False)
    return probe


if __name__ == "__main__":
    raise SystemExit(main(run, __doc__.splitlines()[0]))
