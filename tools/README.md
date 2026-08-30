# tools

Scripts that keep the documentation honest. None of them is part of the server.

## Reference material

| Script | Purpose |
|---|---|
| [`fetch_reference_spec.py`](fetch_reference_spec.py) | Fetch and sanitise the Jellyfin OpenAPI document from a running server into the git-ignored `reference/` directory |
| [`extract_v1_surface.py`](extract_v1_surface.py) | Validate `docs/compatibility/surface.yaml` against that document — the automated half of Principle VI |
| [`generate_cultures.py`](generate_cultures.py) | Regenerate `src/atrium/metadata/cultures.py` — the table `GET /Localization/Cultures` serves — from a measurement of the reference |

The validator refuses a document whose version is not the one `surface.yaml` pins. Fetching from a
`10.11.11` server therefore reports a mismatch against the pinned `10.11.10` contract: see
[reference-target §1](../docs/compatibility/reference-target.md#1-the-pinned-version), which
records why the two differ and what moving the pin costs.

## Probes

A probe answers **one** question about how a real Jellyfin behaves, prints its finding together
with the citation the documentation uses, and **exits non-zero when the finding contradicts what
this repository currently claims**. That last property is what makes them a regression suite for
the project's *beliefs*, not only for its code: when a server upgrade changes a behaviour, the
probe says so instead of the documentation quietly becoming false.

Specified in [specs/010 §3.5](../specs/010-conformance-harness/spec.md).

| Script | Question | Answers | Writes |
|---|---|---|---|
| [`probe_content_type_profiles.py`](probe_content_type_profiles.py) | Does the server answer the three declared JSON content types identically? | 001 §3.0 rule 2 | no |
| [`probe_routing.py`](probe_routing.py) | How does the server match a path to a route, how does it refuse, and which headers ride every response? | 001 §3.6; behaviours §1.9, §1.10, §4.1 | no |
| [`probe_query_envelope.py`](probe_query_envelope.py) | What shape does each list endpoint return, and how does one refuse? | 005 OQ-6, §3.5; behaviours §1.11, §1.12, §1.15, §1.16 | no |
| [`probe_sort_names.py`](probe_sort_names.py) | How does the server derive `SortName` from `Name`? | 003 OQ-3 | yes |
| [`probe_playlist_move.py`](probe_playlist_move.py) | Does `Move`'s `newIndex` refer to the list before or after removal? | 009 OQ-1 | yes |
| [`probe_playstate.py`](probe_playstate.py) | What do playback reports and played marks actually do to `UserData`, what does a playing session show, and how does each route refuse? | 007 §3.2–§3.8, OQ-2/3/5/6, AC-21/AC-22 — and OQ-4 with `--reap`, which costs ten minutes of deliberate silence | yes |
| [`probe_auth_mechanisms.py`](probe_auth_mechanisms.py) | How may a client present a token, how strict is the client header's grammar, what one-off shapes does a sign-in return, and how is a refusal shaped? | 002 §3.1–§3.6, §3.8, OQ-1, OQ-3; behaviours §2.4, §2.10, §2.12–§2.14, §3.5, §5.1, §5.9 | no |
| [`probe_library_extensions.py`](probe_library_extensions.py) | Which file extensions does the reference admit as items, and which does it ignore? | 003 §3.2, OQ-1 | no |
| [`probe_music_precedence.py`](probe_music_precedence.py) | What happens when a file's embedded tags contradict its path? | 003 §3.5, OQ-5 | no |
| [`probe_item_identity.py`](probe_item_identity.py) | What is an item's identifier derived from, and does moving a library root change it? | behaviours §1.4, 003 §3.6 | no |
| [`probe_by_name_normalisation.py`](probe_by_name_normalisation.py) | Does the reference fold case when a genre name becomes an item, or does the list grow duplicates? | 004 §3.7, OQ-3 | no |
| [`probe_sort_stability.py`](probe_sort_stability.py) | What breaks a tie under each `SortBy`, and does paging hold once one is broken? | 005 §3.4, OQ-3 | no |
| [`probe_item_shapes.py`](probe_item_shapes.py) | Which properties does the reference emit per item type, bare and when asked? | 005 §3.2, plan §6.5; behaviours §1.7, §2.17; `MEDIA_TYPE_OF` | no |
| [`probe_next_up.py`](probe_next_up.py) | What does `/Shows/NextUp` call "next", and do specials take part? | 005 §3.7, plan §6.8 | yes |
| [`probe_image_tags.py`](probe_image_tags.py) | Is a stale image `tag` an error, and what is the tag derived from? | 006 §3.4, AC-10, OQ-1, OQ-2, OQ-6 | no |
| [`probe_image_formats.py`](probe_image_formats.py) | What format does a resized image come back in, does a fill box crop, and does a malformed parameter refuse or forgive? Five batteries: the format matrix, the **non-square fill** cells, the **exact `width`/`height`** cells, the **`Accept` negotiation** cells, and which requests come back as the source's own bytes | 006 §3.2, §3.3, AC-6, AC-15, OQ-3, OQ-5; plan §6.3; behaviours §1.17 | no |
| [`probe_by_name_counts.py`](probe_by_name_counts.py) | Is `TotalRecordCount` really 0 on the by-name endpoints when the request has no `limit` — and is `artistIds` really the credit superset? | behaviours §3.1; 005 §3.9 and the credit split | no |
| [`probe_public_info.py`](probe_public_info.py) | What exactly does `/System/Info/Public` return, before any token exists? | 001 §3.1; reference-target §4; behaviours §1.7 | no |
| [`probe_playback_refusal.py`](probe_playback_refusal.py) | When no source can be played by the profile, is it `200` — and does an `ErrorCode` arrive? | 008 §3, the error table | no |
| [`probe_video_stream_for_a_track.py`](probe_video_stream_for_a_track.py) | What does `/Videos/{id}/stream` answer when the id names an audio track? | api-surface §4, §8 | no |
| [`probe_playback_info.py`](probe_playback_info.py) | Are the negotiation's flags per request, do the body switches and the policy bite, when does an `ErrorCode` appear, how do the two routes refuse, and what is "no `DeviceProfile`" negotiated against? | 008 §3.1–§3.3, OQ-1, OQ-2, OQ-12; behaviours §2.21, §2.22 | only under `--allow-writes`: the policy battery, which needs an admin and a throwaway user, and the capabilities battery, which replaces the probe's own session capabilities and restores them |
| [`probe_transcode_decision.py`](probe_transcode_decision.py) | What goes into a `TranscodingUrl`, how many variants does the master playlist advertise **for a standard-range and for a high-dynamic-range source**, and is the accepted stream copied? | 008 §3.3, §3.4, §3.7, OQ-7, OQ-8, OQ-9 | yes — it makes the server encode one segment per half, and the HDR half's is an fMP4 segment of a usually-4K film |
| [`probe_hls.py`](probe_hls.py) | Is the playlist complete up front and uniform, where does its segment cadence come from, and are segments sized, byte-stable and served out of order? | 008 §3.7, §6, OQ-3, plan §6.4 and §6.8's cadence debt; behaviours §2.10, §3.3's HLS half | yes — two short sessions, plus playlist-only reads |
| [`probe_universal_audio.py`](probe_universal_audio.py) | Does `/universal` meet a stated ceiling, when is it an empty `200`, does `enableRedirection` ever fire, and what do the two PCM/WAV symptoms actually answer? | 008 §3.6, OQ-4, AC-19, AC-20, AC-21; behaviours §3.2, §3.7, §3.8 | yes — short audio encodes |
| [`probe_transcode_session.py`](probe_transcode_session.py) | Does production follow the throttle configuration, restart at a seek, stop on `DELETE /Videos/ActiveEncodings`, and die on its own kill timer? | 008 §3.4, §3.8, OQ-6, OQ-10, OQ-11 | yes — several minutes of deliberate encoding |
| [`probe_range_matrix.py`](probe_range_matrix.py) | What does static delivery answer to each shape of `Range` header, and what does a mismatched container suffix serve? | 008 §3.5, AC-11–AC-14, AC-18; behaviours §2.20 | no |
| [`probe_media_container.py`](probe_media_container.py) | What is a file's `Container` at item level and on its media source, and what decides the single form? | 008 §3.1, plan §4 and §6.1 | no |
| [`probe_media_source.py`](probe_media_source.py) | What does a media source carry on a listing, and how is its `ETag` derived? | 008 §3.1, plan §6.1 | no |
| [`probe_decision_ladder.py`](probe_decision_ladder.py) | What does each rung of the ladder answer, in what order are the reasons listed, and at what precision is a ceiling compared? | 008 §3.3, §3.4, AC-1–AC-9; plan §5, §6.2 | no |
| [`probe_progressive_delivery.py`](probe_progressive_delivery.py) | What shape is a progressive answer, what does a `Range` do to one, what does `mediaSourceId` decide, and does a start position seek? | 008 §3.4, §3.5, AC-10, AC-15, AC-17; behaviours §1.11, §3.3, §3.9 | yes — a few seconds of deliberate encoding, every session stopped |
| [`probe_subtitle_negotiation.py`](probe_subtitle_negotiation.py) | Which subtitle properties live where, what does each declared method resolve to per stream, is a posted index read, and what picks the default track? | 011 §3.2, §3.3, OQ-2, OQ-5, OQ-12 | only under `--allow-writes`: a throwaway user whose subtitle mode and language preference the score battery flips, deleted on the way out |
| [`probe_subtitle_manifest.py`](probe_subtitle_manifest.py) | What makes the master playlist announce a subtitle, what does each announcement say verbatim, and where does its name come from? | 011 §3.4, OQ-1, OQ-3, OQ-4 | yes — one play session per negotiation, each stopped; no segment fetched |
| [`probe_subtitle_delivery.py`](probe_subtitle_delivery.py) | What do the subtitle playlist and the subtitle fetch answer — to a caller with no token, to a window, to a format, to a cue sitting exactly on a window boundary, to a track asked for in the format it is already in — windowed or not — and to every way of naming nothing, an item that exists and holds nothing servable included? | 011 §3.5, §3.7, AC-10, OQ-6, OQ-8, OQ-11; behaviours §2.10, §3.12 | only under `--allow-writes`: the image-subtitle case, which the reference attempts with ffmpeg before refusing |
| [`probe_sidecar_subtitles.py`](probe_sidecar_subtitles.py) | Which files beside a media file become subtitle streams, and what does the reference read out of their names? | 011 §3.6, OQ-7; behaviours §5 | no |
| [`probe_progressive_production.py`](probe_progressive_production.py) | Does a capped progressive transcode ever state a length, and is the work keyed on the play session the client supplies? | 011 OQ-9, OQ-10; behaviours §3.3 | yes — two or three short audio transcodes of one track, every session stopped |
| [`probe_uninspected_source.py`](probe_uninspected_source.py) | What does a negotiation answer for a media source nothing has successfully opened, what does a listing answer, and is what an on-demand probe learns kept? | 012 §3.2, §3.4, OQ-1, OQ-2, OQ-3, OQ-9; behaviours §2.23, §3.13, §5 | yes — it builds a library of deliberately unreadable files on the server's own disk, scans, measures, and removes both the libraries and the files |
| [`probe_session_filters.py`](probe_session_filters.py) | What do `GET /Sessions`' three parameters narrow, and does the narrowing run before or after the rule about whose sessions a caller may see? | 002 §3.8 (measured at 012's gate, OQ-7); behaviours §2.25 | only under `--allow-writes`: a throwaway non-administrator whose session supplies the second row, deleted on the way out |

### Running them

Once, to set up:

```bash
cp .env.example .env      # then fill it in
```

Then:

```bash
python3 tools/probe_content_type_profiles.py
python3 tools/probe_routing.py
python3 tools/probe_query_envelope.py
python3 tools/probe_sort_names.py     --allow-writes
python3 tools/probe_playlist_move.py  --allow-writes
python3 tools/probe_playstate.py      --allow-writes
python3 tools/probe_auth_mechanisms.py --disabled-user probe-disabled
python3 tools/probe_library_extensions.py
python3 tools/probe_music_precedence.py
python3 tools/probe_item_identity.py
python3 tools/probe_by_name_normalisation.py
python3 tools/probe_sort_stability.py
python3 tools/probe_item_shapes.py
python3 tools/probe_next_up.py       --allow-writes
python3 tools/probe_image_tags.py
python3 tools/probe_image_formats.py
python3 tools/probe_playback_refusal.py
python3 tools/probe_playback_info.py --allow-writes
python3 tools/probe_transcode_decision.py --allow-writes
python3 tools/probe_hls.py           --allow-writes
python3 tools/probe_universal_audio.py --allow-writes
python3 tools/probe_transcode_session.py --allow-writes
python3 tools/probe_range_matrix.py
python3 tools/probe_media_container.py
python3 tools/probe_media_source.py
python3 tools/probe_decision_ladder.py
python3 tools/probe_progressive_delivery.py --allow-writes
python3 tools/probe_subtitle_negotiation.py --allow-writes
python3 tools/probe_subtitle_manifest.py --allow-writes
python3 tools/probe_subtitle_delivery.py --allow-writes
python3 tools/probe_sidecar_subtitles.py
python3 tools/probe_progressive_production.py --allow-writes
python3 tools/probe_session_filters.py --allow-writes
```

`probe_uninspected_source.py` is the exception to the list above, and it says so in its own
docstring: its question cannot be asked of a remote server, because the fixture it needs is a file
the server can see and this machine can write. Every item in a real library has been probed — the
scan that creates an item is the scan that probes it — so the state only exists where the probe
*failed*, and the probe has to manufacture it:

```bash
docker run -d --name jf -p 8097:8096 -v "$PWD/fixture:/media" jellyfin/jellyfin:10.11.11
#  … complete the startup wizard …
python3 tools/probe_uninspected_source.py http://127.0.0.1:8097 -u admin \
    --allow-writes --fixture-root "$PWD/fixture" --server-root /media
```

The playback probes marked `--allow-writes` make the reference **encode**: each starts one
or two short transcoding sessions, fetches a handful of segments or the first bytes of a
stream, and stops its sessions on the way out — including on failure. They are the measured
ground under 008's spec review, and `probe_transcode_session.py` deliberately spends about a
minute watching the throttle. `_playback.py` is their shared plumbing: every profile is built
against the source the library actually offers, which is what lets them run against any
Jellyfin rather than one seeded library.

`probe_item_identity.py` is the one probe here that confirms a `[source: …]` citation from
**outside** the source: it recomputes each item's id from that item's own reported path and
compares. A source citation says what the code appears to do; this says what the server did. It
also reports what it *cannot* answer — a server with `EnableCaseSensitiveItemIds` set says nothing
about the reference's default for it.

The two 003 naming probes **write nothing and need no fixture placed anywhere**. They read the library the
server already has: the item list for what it admitted, and `/Environment/DirectoryContents` — the
read-only filesystem view the library-setup screen uses — for what was on disk and became nothing.
Both therefore measure *that* library rather than the reference's configured lists, and each says
in its own output which half of its finding is a measurement and which is a bound.

`generate_cultures.py` is the one script here that **writes into `src/`**, and it reports like a
probe for exactly that reason: it prints what it measured, says whether the committed table
changed, and exits non-zero if the response no longer has the shape the table was built from. The
list it produces is **not** the Library of Congress ISO 639-2 registry — see the script's own
docstring for the measurement that settled that, and `--from-file` for running it against a saved
response rather than a server.

```bash
python3 tools/generate_cultures.py
python3 tools/generate_cultures.py --from-file cultures.json
```

The **five subtitle probes** were written for 011's spec review and share `_playback.py`'s
subtitle helpers, which find a source of the shape each battery needs — a text track, an image
track beside it, an external file, or two streams that tie on score — rather than assuming a
seeded library. Two of them reproduce the reference rather than describing it, which is what makes
them able to fail: `probe_sidecar_subtitles.py` predicts, for every file in a media directory,
whether it becomes a stream and what language, flags and title it carries, and compares that with
what the server reported; `probe_subtitle_negotiation.py` recomputes each stream's ranking score
from the stream's own properties and compares it with the emitted one. A rule that is wrong shows
up as a mismatch rather than as prose nobody checks.

`probe_subtitle_negotiation.py`'s score battery needs an **administrator**, for the same reason
`probe_playback_info.py`'s policy battery does and a different one: the default subtitle track is
a function of a *user's* subtitle mode and language preference, and the only way to vary those is
to own an account. It creates `atrium-probe-subs`, flips its configuration, and deletes it on the
way out including on failure.

`probe_item_shapes.py` asks for **every member of the server's own `ItemFields` enum**, read from
`/api-docs/openapi.json`, rather than the names the specification happens to list. That is what
makes "gated" a measurement rather than a restatement of the claim, and it is why the probe still
works when the specification is wrong about which names exist. Without the document it falls back
to the specification's own list and says so.

It samples up to twelve items per type and reports presence as `12/12`, not as a boolean, because
a null property is omitted (behaviours §1.7): one sample cannot tell a gated field from a field
that is null on that item. It classifies over `/Items` alone and reports `/UserViews` separately —
folding them together let one fat row promote a gated name to "per-type" for every content type at
once, which is what its first run did.

`probe_library_extensions.py` walks a bounded number of directories, because the tree belongs to
somebody else; `--listings` and `--per-root` widen it, and it always reports what it did not
reach.

`probe_auth_mechanisms.py` needs one thing the others do not: **an account that is disabled on the
reference**, because measuring how a disabled user is refused is the whole of 002 OQ-3 and there is
no way to make one from here. Create an account nobody uses, disable it, and name it. Without it the
probe prints every other finding and exits `2` rather than guessing which account to try — guessing
means failed logins against somebody else's.

It never tests lockout. Failing N logins on purpose would lock a real account, and the counter it
moves is not one a probe can reset.

**If a probe cannot verify the server's certificate**, the cause is usually local rather than the
server's. A Python installed from python.org ships **no CA bundle at all** — `ssl` reports zero
trusted certificates — so an HTTPS reference fails with `CERTIFICATE_VERIFY_FAILED` while `curl`
against the same URL succeeds, which reads like a server fault and is not one. Run that Python's
`Install Certificates.command`, or point `SSL_CERT_FILE` at a bundle for one run:

```bash
SSL_CERT_FILE=$(python3 -c "import certifi; print(certifi.where())") python3 tools/probe_music_precedence.py
```

The macOS system bundle at `/etc/ssl/cert.pem` is **not** always a substitute: it is missing roots
that `curl` reaches through the keychain instead, so it can fail where the keychain succeeds.

`.env` is git-ignored and holds a real password for a real server. The template is committed; the
file it produces never is. Leaving `JELLYFIN_PASSWORD` empty is the safer choice — the probe
prompts instead, and nothing is stored.

Every value can still be given on the command line, and a real environment variable beats the
file, so one probe can be pointed elsewhere for a single run without editing anything:

```bash
JELLYFIN_URL=http://other-server:8096 python3 tools/probe_query_envelope.py
```

The `.env` reader is fifteen lines in `_probe.py` rather than a dependency, for the same reason
everything else here is: a probe runs before any environment is built.

**Exit codes:** `0` the finding agrees with the documentation, or the documentation had an open
question and now has an answer. `1` the finding **contradicts** the documentation — read the
message, it names the section to change. `2` the question could not be answered at all.

### Writes

Four of the probes cannot answer their question without writing, and they say so rather than doing
it quietly: each refuses to run without `--allow-writes`.

| Probe | What it creates | Cleanup |
|---|---|---|
| `probe_sort_names.py` | 15 empty playlists with crafted names | Deletes them, including on failure |
| `probe_playlist_move.py` | 2 playlists | Deletes them, including on failure |
| `probe_playstate.py` | Play state and favourite marks on one long item, one short item, one season's episodes and one artist; a live playback reported and stopped | Chooses only items with no user data at all, so restoring them is exact; sweeps the season's episodes and the artist's favourite clean including on failure, and stops the playback it started |
| `probe_next_up.py` | Played marks on a handful of episodes | Chooses series whose episodes carry no user data, deletes every mark including on failure, and verifies the episodes pristine afterwards |

`probe_playstate.py` refuses to run at all if it cannot find a long item with no existing user
data. It will not overwrite a real resume position, because it could not put one back exactly.

### Planned

| Script | Purpose | Arrives with |
|---|---|---|
| `differential.py` | Issue the same request to Atrium and a real Jellyfin and compare field by field (L3) | Feature 010 |
| `probe_item_ids.py`, `probe_wire_format.py`, … | The remaining prior-measurement debts in [reference-target.md](../docs/compatibility/reference-target.md) | Their owning features |

A runner that executes every probe and summarises is deliberately **not** here yet: it is part of
the harness feature 010 specifies, and building it before that spec is accepted would be
short-circuiting the method (Principle III).

## Conventions

**Python 3.9 or newer** — deliberately lower than the 3.12 the server requires
([ADR-0002](../docs/decisions/0002-python-and-the-runtime-stack.md)). A probe is meant to be run
against a server *before* any environment exists, often on a machine that is not a development
box, so it has to work with the interpreter that is already there. macOS ships 3.9, and so does
the one inside Xcode's toolchain, which is what `python3` resolves to on a Mac with Xcode
installed and nothing else.

That means `from __future__ import annotations` at the top of every probe, and no syntax newer
than 3.9 outside annotations. It is a constraint, not an accident: verified at both ends of the
range — the full CLI and every pure function under **3.9.6**, and every module under **3.14.6**.

**Dependency-free.** These run in CI before any environment is built, so they use only the
standard library. `surface.yaml` is a deliberately flat subset of YAML for the same reason, and
the probes share [`_probe.py`](_probe.py) rather than a package.

**Credentials are never taken from the command line by preference.** `JELLYFIN_PASSWORD`, or an
interactive prompt. `--password` exists and is documented as discouraged, because it is visible in
the process list. No probe logs a password at any level.

**Probes record their own provenance.** Every one prints
`[probe: tools/probe_x.py, Jellyfin <version>, <date>]` — the exact form the documentation cites.
A measurement whose server version is unknown is not a measurement.

**Nothing here writes into the repository except by explicit flag.** Fetched reference material
goes to `reference/`, which is git-ignored.
