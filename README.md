# Atrium Media Server

[![CI](https://github.com/vdatanet/atrium-media-server/actions/workflows/ci.yml/badge.svg)](https://github.com/vdatanet/atrium-media-server/actions/workflows/ci.yml)

Atrium is a media server for **movies, TV series and music**, written from scratch in Python,
that speaks the **Jellyfin HTTP API**.

It is not a fork of Jellyfin, and it is not a new protocol. It is an independent implementation
of an existing, widely deployed contract. The goal is that an existing Jellyfin client — one that
was never modified, recompiled or configured for Atrium — points at an Atrium instance and simply
works.

## Why this exists

The project has two honest reasons, and it helps to keep them apart:

1. **Didactic.** A media server is a good teacher. It touches filesystem scanning, metadata
   resolution, content negotiation, HTTP range delivery, transcoding pipelines, session state and
   a large legacy API surface with real-world quirks. Building one against a *specified* target is
   harder and more instructive than building one against your own imagination, because the target
   does not move when you find it inconvenient.
2. **Practical.** The author maintains multi-server clients that drive Emby and Jellyfin. A server
   that speaks the same protocol is a *programmable server for testing* those clients — with a
   library you control, states you can force, and failures you can inject.

Both reasons collapse into a single design rule, stated in the [constitution](docs/constitution.md):
**the client must not be able to tell.**

## Status

**Nine of twelve features are implemented.** 001 through 008 are done — identity and discovery,
authentication and sessions, scanning, metadata, the item query API, images, user data and
playstate, and as of 2026-08-29 playback negotiation and delivery — and 011 (subtitle delivery)
landed on 2026-08-31. 009 (playlists) and 010 (the conformance harness) are specified and still
drafts; 012 (negotiation inputs) is accepted and not yet built. The
[status table](specs/README.md) is the authority; this paragraph is not.

The first request a Jellyfin client makes is answered the way it expects:

```
$ atrium --data-dir /tmp/demo &
$ curl -s localhost:8096/System/Info/Public
{"LocalAddress":"http://127.0.0.1:8096","ServerName":"atrium","Version":"10.11.11",
 "ProductName":"Jellyfin Server","OperatingSystem":"","Id":"…","StartupWizardCompleted":false}
```

And the last one it makes before playing something — `POST /Items/{itemId}/PlaybackInfo` — is
answered by the decision ladder of
[008](specs/008-playback-negotiation-and-delivery/spec.md): direct play, remux, or software
transcoding delivered over HLS, with `Range` support, a supervised encoder per session, and the
operator's throttling and scratch ceilings enforced.

Every change goes through the same gate, locally and in
[CI](.github/workflows/ci.yml) — `ruff`, `mypy --strict`, the test suite on the oldest and newest
supported Python, and the two checks that keep the documentation honest. **No job contacts a
Jellyfin server**: the probes that measure one are run by hand, and the suite fails any test that
opens a TCP connection.

Start here:

| Document | What it settles |
|---|---|
| [docs/constitution.md](docs/constitution.md) | The principles that override every other decision |
| [docs/README.md](docs/README.md) | Map of the documentation and how SDD is practised here |
| [docs/roadmap.md](docs/roadmap.md) | What v1 is, what it is not, and in what order |
| [docs/compatibility/api-surface-v1.md](docs/compatibility/api-surface-v1.md) | The 58 endpoints v1 must serve, and where that number comes from |
| [specs/](specs/) | Feature specifications, one numbered directory each — and the status table |
| [AGENTS.md](AGENTS.md) | How to work on this: the rhythm, the gates, and the habit that finds things |

## Scope of v1

**In:** movies, TV series (seasons/episodes), music (artists/albums/tracks/playlists); library
scanning and identification; metadata from local sidecars, embedded tags and online providers;
user accounts, authentication and per-user play state; image delivery; playback negotiation with
direct play, stream remuxing and software transcoding.

**Out:** live TV, DVR, channels, plugins, DLNA, SyncPlay, hardware-accelerated transcoding,
subtitle burn-in, book/photo libraries, the official Jellyfin web UI.

The full boundary, with reasoning, is in [docs/roadmap.md](docs/roadmap.md).

## Language

**All code, comments, commit messages, identifiers and documentation in this repository are in
English.** No exceptions — including for contributors whose working language is not English.

## Licence

**GPL-3.0-or-later.** See [`LICENSE`](LICENSE) for the full text and
[ADR-0005](docs/decisions/0005-licence.md) for why copyleft rather than a permissive licence — the
short version is that Atrium is written while reading GPL-licensed source as a behavioural
reference, and a compatible copyleft licence makes that method safe by construction.

Atrium is an independent implementation of Jellyfin's API. It is not affiliated with, endorsed by,
or derived from the Jellyfin project's code.
