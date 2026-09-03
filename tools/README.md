# tools

Scripts that keep the documentation honest. None of them is part of the server.

## Reference material

| Script | Purpose |
|---|---|
| [`fetch_reference_spec.py`](fetch_reference_spec.py) | Fetch and sanitise the Jellyfin OpenAPI document from a running server into the git-ignored `reference/` directory |
| [`extract_v1_surface.py`](extract_v1_surface.py) | Validate `docs/compatibility/surface.yaml` against that document — the automated half of Principle VI |
| [`generate_cultures.py`](generate_cultures.py) | Regenerate `src/atrium/metadata/cultures.py` — the table `GET /Localization/Cultures` serves — from a measurement of the reference |

The validator refuses a document whose version is not the one `surface.yaml` pins. Both now read
`10.11.11`, so a document fetched from the reference server validates — which it could not do until
2026-09-01, when the contract pin moved off a `10.11.10` document nobody could obtain. What that
cost and why it was done is [reference-target §1](../docs/compatibility/reference-target.md#1-the-pinned-version).

**A fetched document is the core API plus that server's plugins.** Two of the reference server's
paths come from one, and an earlier fetch — from a server carrying a plugin this one does not —
put nineteen names that were never Jellyfin's into `docs/compatibility/property-names.json`, where
they sat unnoticed for the life of the project. Regenerate the index from a server you know the
plugin list of.

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
| [`probe_playlist_move.py`](probe_playlist_move.py) | Does `Move`'s `newIndex` refer to the list before or after removal, does that reading hold for **every** (source, target) pair, what do its boundaries do, **what does each of its three path segments accept**, and is a playlist entry's identifier its own? | 009 OQ-1, OQ-6, §3.1, §3.5, §6; behaviours §2.7, §2.8, §2.26, §3.15, §3.19 | yes |
| [`probe_playlist_creation.py`](probe_playlist_creation.py) | What does `POST /Playlists` refuse, **in what bytes**, and what does it create — and does the deprecated query form still work? | 009 §3.2, §4, AC-2, AC-3; behaviours §1.11, §1.12, §3.19 | yes |
| [`probe_playlist_media_type.py`](probe_playlist_media_type.py) | Is a playlist's `MediaType` a property of its type, of its creation, or of its contents — and does `mediaTypes=` filter playlists by the row or by the type? | 009 §3.2, §4; plan §4.2; `MEDIA_TYPE_OF` | yes |
| [`probe_playlist_writes.py`](probe_playlist_writes.py) | What does a write do to the entries a playlist already holds — is a repeat dropped in place, does a removal renumber, and **is the de-duplication reliable**? | 009 §3.1, §3.4, AC-5; plan §6.2, §6.3; behaviours §3.18 | yes |
| [`probe_playlist_expansion.py`](probe_playlist_expansion.py) | Does adding a container add its children, in what order, **and which kinds of container** — on the add route and on creation, where it also settles the media type? | 009 OQ-3, §3.2, §3.4, AC-7; plan §6.2 | yes |
| [`probe_playlist_add_remove.py`](probe_playlist_add_remove.py) | What do the add and remove routes accept and refuse, **in bytes** — and is an unknown item id really always skipped? | 009 §3.4, §3.5, AC-5, AC-6; behaviours §1.11, §3.19 | yes |
| [`probe_playlist_visibility.py`](probe_playlist_visibility.py) | What can a user who does not own a playlist see and do — and **what shape is each `403` it can produce**? | 009 OQ-4, §3.6, §3.7, §3.8, AC-12 to AC-19; behaviours §1.11, §3.16, §3.17, §4.3 | yes |
| [`probe_playlist_shares.py`](probe_playlist_shares.py) | Which of the playlists a fixture world would seed can a create body actually produce — a share without `CanEdit`, a public one, and one whose entries come from two libraries — and **which refusal wins when a caller who may not edit names an index the reference crashes on**? | 009 T5, §3.7, AC-14, AC-15, AC-17; plan §4.2, §6.4.1, §8; behaviours §1.11, §3.15 | yes |
| [`probe_playlist_rename.py`](probe_playlist_rename.py) | Who can rename a playlist, and through which route? | 009 §2, §3.8, AC-18; behaviours §5 | yes |
| [`probe_playlist_read.py`](probe_playlist_read.py) | **How wide is a playlist entry row**, which of the declared parameters does the read route honour, and **which error shape is its `404`**? | 009 §3.1, §3.3, AC-4, AC-8; plan §6.5; behaviours §1.11 | yes |
| [`probe_item_deletion.py`](probe_item_deletion.py) | What does `DELETE /Items/{itemId}` answer, to whom, and **in what bytes** — and does it hide a playlist the caller may not read? | 009 §3.6, §3.7, AC-12, AC-13; plan §6.6; behaviours §1.11, §3.20, §4.3 | yes |
| [`probe_user_read.py`](probe_user_read.py) | **Who may read whom** through `GET /Users/{userId}`, what comes back, and what the two identifiers that name nobody answer? | 002 §3.7, AC-7, §6; behaviours §1.11, §3.5, §3.22 | yes |
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
| [`probe_playback_info.py`](probe_playback_info.py) | Are the negotiation's flags per request, do the body switches and the policy bite, when does an `ErrorCode` appear, how do the two routes refuse, what is "no `DeviceProfile`" negotiated against — and does a **listing** carry the same permissions, on whose account, and on a source nothing inspected? | 008 §3.1–§3.3, OQ-1, OQ-2, OQ-12; 005 §3.2; behaviours §2.21, §2.22, §2.23 | only under `--allow-writes`: the policy battery, which needs an admin and a throwaway user, and the capabilities battery, which replaces the probe's own session capabilities and restores them |
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
| [`probe_subtitle_manifest.py`](probe_subtitle_manifest.py) | What makes the master playlist announce a subtitle, which spellings of that one word announce and which of them refuse, does **every** variant line of a multi-variant master carry the group, what does each announcement say verbatim, and where does its name come from? | 011 §3.4, OQ-1, OQ-3, OQ-4; plan §6.8 | yes — one play session per negotiation, each stopped; no segment fetched. The vocabulary and multi-variant batteries build the master address by hand and negotiate nothing |
| [`probe_subtitle_delivery.py`](probe_subtitle_delivery.py) | What do the subtitle playlist and the subtitle fetch answer — to a caller with no token, to a window, to a format, to a cue sitting exactly on a window boundary, to a track asked for in the format it is already in — windowed or not — and to every way of naming nothing, an item that exists and holds nothing servable included? Which parameter each route names when the identifier is not one, and does any source in the library state no runtime? | 011 §3.5, §3.7, AC-10, AC-16, OQ-6, OQ-8, OQ-11; behaviours §2.10, §3.12 | only under `--allow-writes`: the image-subtitle case, which the reference attempts with ffmpeg before refusing |
| [`probe_sidecar_subtitles.py`](probe_sidecar_subtitles.py) | Which files beside a media file become subtitle streams, and what does the reference read out of their names? | 011 §3.6, OQ-7; behaviours §5 | no |
| [`probe_stream_display_title.py`](probe_stream_display_title.py) | What is a subtitle stream's display title assembled from, and which of its pieces are localised rather than literal? | 011 §3.2, OQ-4, plan §6.4; behaviours §5 | no |
| [`probe_progressive_production.py`](probe_progressive_production.py) | Does a capped progressive transcode ever state a length, and is the work keyed on the play session the client supplies? | 011 OQ-9, OQ-10; behaviours §3.3 | yes — two or three short audio transcodes of one track, every session stopped |
| [`probe_uninspected_source.py`](probe_uninspected_source.py) | What does a negotiation answer for a media source nothing has successfully opened, what does a listing answer, and is what an on-demand probe learns kept? | 012 §3.2, §3.4, OQ-1, OQ-2, OQ-3, OQ-9; behaviours §2.23, §3.13, §5 | yes — it builds a library of deliberately unreadable files on the server's own disk, scans, measures, and removes both the libraries and the files |
| [`probe_session_filters.py`](probe_session_filters.py) | What do `GET /Sessions`' three parameters narrow, and does the narrowing run before or after the rule about whose sessions a caller may see? | 002 §3.8 (measured at 012's gate, OQ-7); behaviours §2.25 | only under `--allow-writes`: a throwaway non-administrator whose session supplies the second row, deleted on the way out |
| [`probe_similar_ranking.py`](probe_similar_ranking.py) | Does the reference rank `Similar`, and does its `limit` mean what it says? | 010 §7 OQ-4 and the G-2 row; 005 §3.7, OQ-5 | no |
| [`probe_differential_join.py`](probe_differential_join.py) | What can join an item on two servers whose identifiers are derived differently? | 010 §3.2, §7 OQ-1; behaviours §1.4, §3.6 | no |
| [`probe_reference_determinism.py`](probe_reference_determinism.py) | Does the reference answer the same request the same way twice? | 010 §3.3, §7 OQ-3, OQ-4; behaviours §1.9 | no |
| [`probe_restricted_surface.py`](probe_restricted_surface.py) | How much of the surface answers differently to a restricted non-administrator? | 010 §3.9, §3.10, AC-14, AC-15; behaviours §3.16, §3.17 | yes |
| [`probe_reference_scan.py`](probe_reference_scan.py) | Given this repository's fixture tree, what does a reference server's library contain — and how much of that reading came from a metadata provider rather than from the tree? | 010 §3.1, AC-2, AC-7, AC-8; plan §6.6, §11 D-4 | yes, and **only to an instance it creates and destroys** |
| [`probe_public_users.py`](probe_public_users.py) | Does `/Users/Public` answer an empty list when every account is hidden from the login screen? | 010 §3.5, AC-9; reference-target §2; behaviours §2.2 | yes, and **only to an instance it creates and destroys** |
| [`probe_local_address.py`](probe_local_address.py) | Does `LocalAddress` advertise the HTTPS scheme and port once a certificate is configured, on a request that came in over HTTP? | 010 §3.5, AC-9; reference-target §2; behaviours §2.3, §4.2; 001 §3.4 | yes, and **only to an instance it creates and destroys** |
| [`probe_user_views_parent.py`](probe_user_views_parent.py) | What does a `/UserViews` row carry in `ParentId`, and on which rows? | behaviours §1.7; 005 §3.2 and notes/item-shapes.md §6 | yes, and **only to an instance it creates and destroys** |

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
python3 tools/probe_playlist_creation.py   --allow-writes
python3 tools/probe_playlist_expansion.py  --allow-writes
python3 tools/probe_playlist_add_remove.py --allow-writes
python3 tools/probe_playlist_visibility.py --allow-writes
python3 tools/probe_playlist_rename.py     --allow-writes
python3 tools/probe_playlist_read.py       --allow-writes
python3 tools/probe_user_read.py           --allow-writes
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
python3 tools/probe_stream_display_title.py
python3 tools/probe_progressive_production.py --allow-writes
python3 tools/probe_session_filters.py --allow-writes
```

**Four probes are not in the list above because they take no server at all**, and each refuses one
that is offered: `probe_reference_scan.py`, `probe_public_users.py`, `probe_local_address.py` and
`probe_user_views_parent.py` stand up a single-use instance of the pinned version, ask it their
question and destroy it. Each needs a container runtime and nothing else:

```bash
python3 tools/probe_reference_scan.py     --allow-writes
python3 tools/probe_public_users.py       --allow-writes
python3 tools/probe_local_address.py      --allow-writes   # also needs openssl on the PATH
python3 tools/probe_user_views_parent.py  --allow-writes
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

The **six subtitle probes** — five written for 011's spec review and one at T10 — share
`_playback.py`'s subtitle helpers, which find a source of the shape each battery needs — a text
track, an image track beside it, an external file, or two streams that tie on score — rather than
assuming a seeded library. Three of them reproduce the reference rather than describing it, which
is what makes them able to fail: `probe_sidecar_subtitles.py` predicts, for every file in a media
directory, whether it becomes a stream and what language, flags and title it carries, and compares
that with what the server reported; `probe_subtitle_negotiation.py` recomputes each stream's
ranking score from the stream's own properties and compares it with the emitted one; and
`probe_stream_display_title.py` rebuilds every subtitle stream's display title from that stream's
own properties, after reading the one piece it cannot compute — the language name — off the
streams that state a language and no title of their own. A rule that is wrong shows up as a
mismatch rather than as prose nobody checks.

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
message, it names the section to change. `2` the question could not be answered at all. `3` the run
created something on the server that it could not remove and nothing explains why — a leak, and a
defect in the probe rather than a finding.

### Writes

The probes that cannot answer their question without writing say so rather than doing it quietly:
each refuses to run without `--allow-writes`, and `tests/unit/test_probe_convention.py` fails a
probe that reaches a write route without declaring it — which caught two on 2026-09-02 that had
been creating user accounts without asking.

| Probe | What it creates | Cleanup |
|---|---|---|
| `probe_sort_names.py` | 15 empty playlists with crafted names | Deletes them, including on failure |
| `probe_playlist_move.py` | 2 playlists, plus one per boundary case, one per addressing case and one per (source, target) pair | Deletes them, including on failure |
| `probe_playlist_creation.py` | Up to 17 playlists, including ones named badly on purpose and several made through the query form | Deletes them, including on failure |
| `probe_playlist_expansion.py` | 1 playlist per container kind, plus one per creation case — and one of them holds a whole library, so it picks the **smallest** library root there is | Deletes them, including on failure |
| `probe_playlist_add_remove.py` | 1 playlist per identifier class, on both routes | Deletes them, including on failure |
| `probe_playlist_visibility.py` | A throwaway non-administrator user, whose library access it restricts, and 2 playlists (a third is attempted and refused, which is the measurement) | Deletes all three, including on failure. Refuses to run if a user of that name already exists, so it can never touch a real account |
| `probe_playlist_rename.py` | A throwaway non-administrator user and 2 playlists | The same. It renames nothing it did not create: that route writes metadata through the savers, so pointing it at a library item would be an edit, not a measurement |
| `probe_user_read.py` | Two throwaway non-administrator users, one of them restricted to a single library | Deletes both, including on failure. Refuses to run if a user of either name already exists, so it can never touch a real account — and it only ever *reads* the operator's own administrator account |
| `probe_playstate.py` | Play state and favourite marks on one long item, one short item, one season's episodes and one artist; a live playback reported and stopped | Chooses only items with no user data at all, so restoring them is exact; sweeps the season's episodes and the artist's favourite clean including on failure, and stops the playback it started |
| `probe_restricted_surface.py` | A throwaway non-administrator user restricted to one library, and 1 private playlist holding an item from that library and an item from outside it | Deletes both, including on failure. Refuses to run if a user of that name already exists, so it can never touch a real account |
| `probe_next_up.py` | Played marks on a handful of episodes | Chooses series whose episodes carry no user data, deletes every mark including on failure, and verifies the episodes pristine afterwards |
| `probe_public_users.py` | A whole server: a single-use instance, plus one throwaway account on it, and every account's `IsHidden` flipped in both directions | Destroys the container, its volumes and everything inside them. Refuses a server argument outright: hiding every account changes what an operator's login screen shows |
| `probe_local_address.py` | A whole server: a single-use instance given a throwaway self-signed certificate, HTTPS turned on, and restarted so the certificate is read | The same, and the certificate is generated into a git-ignored directory that goes with the run. Refuses a server argument outright |
| `probe_reference_scan.py` | Two whole servers: a single-use reference instance each for its two readings, three libraries scanned into each | Destroys the container, its volumes and everything written inside them, on both paths — and refuses a server argument outright, because its question cannot be asked without writing a library into the server being asked. **One of the four writing probes that can never touch an operator's data** — the two above it and the one below it are the others — which is the argument [ADR-0007](../docs/decisions/0007-a-container-runtime-for-the-reference-instance.md) makes in one line |
| `probe_user_views_parent.py` | A whole server: a single-use instance over four empty libraries, plus a throwaway seat, one playlist, the administrator's grouping preference and the server-wide `Folders` view | The same, and it deletes the seat and the playlist itself rather than leaving them to the shared register. Refuses a server argument outright: its six readings need libraries added, grouped and a server-wide view switched, which is not something to do to somebody's installation |

`probe_playstate.py` refuses to run at all if it cannot find a long item with no existing user
data. It will not overwrite a real resume position, because it could not put one back exactly.

**The Cleanup column above was the intent, and on 2026-09-01 it was checked and did not hold.** The
server 009's probes ran against still held **28 playlists** created by them, all carrying the name
those probes create them under: *"deletes them, including on failure"* described what each probe
was written to do, and each of them had written it separately.

**Since 2026-09-02 it is a mechanism instead of a column** (010 T13). `_probe.py` holds one
**created-and-owned register**: `Server` records a creation as it happens — `POST /Playlists` and
`POST /Users/New` are the two routes that make something outliving the request — a removal the
probe issues itself de-registers what it removed, and `main` tears down whatever is left **in a
`finally`**, so a probe that fails on any path out still removes what the run made. A probe no
longer has to remember, which is the difference between the contract and the claim: the
twenty-eight scripts that already wrote keep the teardowns they have and the register sees nothing
to do, and the twenty-ninth is covered without being edited.
`tests/unit/test_probe_convention.py` drives it with a run that raises and fails if that `finally`
is deleted.

**Three teardown failures are not leaks, and the run says which it was.** A `401` means the token
was revoked out from under the run — the reference binds a token to a device, so two accounts on
one device were one session until each account got a device of its own (010 T12, T13); a connection
refused means the server stopped answering, which the single-use instance does often enough to have
been counted; and a `404` means it was already gone. Only an unexplained failure exits `3`, because
an enforcement that cries wolf is one nobody reads.

It is also the second reason [010 §3.1](../specs/010-conformance-harness/spec.md) has a run stand up
a disposable reference instance of its own: against an instance that is destroyed either way, a
leaked artefact costs nothing.

### The differential harness

`differential.py` is not a probe: it answers no single question and it contradicts no
documentation. It issues the same request to Atrium and to a real Jellyfin, as each identity it
authenticates as, and writes the report [010 §3.4](../specs/010-conformance-harness/spec.md)
specifies — which is the deliverable, and not a pass/fail line.

```bash
python3 tools/differential.py --atrium http://localhost:8096 --jellyfin http://your-jellyfin:8096
```

**It writes to the reference, and what it writes is a seat.** A run creates a restricted
non-administrator on **each** server that can make one — a seat is an account and the two do not
share one — and destroys both, on the success path and on the exception path alike. It refuses to
start when a seat under its own fixed name is already there, because such a seat is either another
run in flight or the wreckage of one (AC-15). The request cases that change user data name that
created seat and never the administrator's, whose account is the operator's own.

**Atrium cannot make one, so on that side the seat is handed in.** The three routes a seat is made
with — `GET /Users`, `POST /Users/New`, `POST /Users/{userId}/Policy` — are the reference's, and
none of them is in [surface.yaml](../docs/compatibility/surface.yaml): Principle VI keeps an
endpoint out until a client is measured calling it, and neither analysed client administers
accounts. Provision the seats yourself, narrow the reader to one library, and name them:

```bash
export ATRIUM_RESTRICTED_USERNAME=… ATRIUM_RESTRICTED_PASSWORD=…
export ATRIUM_PLAYBACK_DENIED_USERNAME=… ATRIUM_PLAYBACK_DENIED_PASSWORD=…
```

A handed seat is signed in as, used, and **left exactly where it was** — `created_by_the_run` is
false for it, which is what keeps the teardown away from somebody's account. The same pair exists
under `JELLYFIN_` for a reference somebody else is running.

**A `--fixture` run stands the instance up first and compares against it.** `--fixture` means the
fixture on *both* servers, so the instance **is** the reference for that run: its wizard's
administrator is the account the run holds, and a `--jellyfin` naming anything else is refused.
The tree is built through `tests/fixtures/reference_tree.py` into `reference/fixture-tree` unless
`--fixture-root` names another, and the instance is given the **six typed libraries** that module
declares.

**The Atrium half of that is yours to arrange, and there is no command for it.** A running Atrium
cannot be given a library: `atrium.library.config.create` and `atrium.library.scan.scan` have no
caller outside the test suite, and `config.toml` has no libraries section — the roadmap files
library administration under [v2's CLI](../docs/roadmap.md#v2--the-management-cli) and names direct
database access as v1's way. So a `--fixture` run stands the tree up on the reference and compares
it against whatever library the Atrium you point at happens to hold, and the `needs: fixture`
request cases resolve their anchors on each server separately. **AC-2 is checked without a live
Atrium for exactly this reason**: `tools/probe_reference_scan.py` records the reference's reading
into `docs/compatibility/reference-fixture-reading.json` and
`tests/library/test_reference_reading.py` compares Atrium's own scan of the same tree against it, in
the default job, with no Jellyfin anywhere.

**What arranging it actually costs, measured on the first complete sweep (2026-09-03), because
"yours to arrange" was true and unhelpful.** Four things, all through `atrium.*` in a throwaway
script and none of them through a route:

1. **The six libraries of `tests/fixtures/reference_tree.py`, over the same tree, by the same
   names.** `library.config.create` then `library.scan.scan`, one per library. Give them different
   names and the two `/UserViews` no longer line up.
2. **An administrator**, through `UserRepository.add` with a hash from `users.passwords.build`.
3. **A restricted seat, handed in under `ATRIUM_RESTRICTED_*`** — Atrium cannot make one, which is
   the paragraph above. It must be narrowed to **the same library the reference narrows its own
   created seat to**, which is `movies_library_id`'s choice: the first `movies` view *with
   something in it*, so `Films` and not `Movies` on this fixture. Narrowed to the other one, 21 of
   the restricted seat's cases cannot resolve an anchor and are reported not asked — correctly, and
   about a seat nobody meant to build.
4. **A policy and a configuration on both accounts, seeded from the reference's own documents.**
   This is the one that is not tidiness. Atrium has **no route that gives an account a policy** —
   `POST /Users/{userId}/Policy` is not in the surface — so an account made by direct database
   access answers **11 of the reference's 42 policy properties and an empty `Configuration`**, and
   every `GET /Users/Me` in the report then carries 15 `MISSING_KEY` findings about *how the
   account was made* rather than about this server. Seed both through `atrium.users.policy.split`,
   which is the reader that route would use, and the report measures the server again.

None of the four is a defect and none is in scope for 010 (spec §2); they are what the missing
management surface costs a run, written down so the next one does not rediscover them.

**`--ignored-parameters` writes the second report.** Pointed at Atrium's data directory, or at the
`ignored-parameters.json` in it, the run also writes
`reference/ignored-parameters-<date>.md` — [010 §3.6](../specs/010-conformance-harness/spec.md)'s
parameter, endpoint, count and client. **It is the tally that server wrote when it last stopped**,
never this run's own sweep: the count is complete only after the last request a route could have
answered, which is the same sentence as *"it is a file and not an endpoint"*. An endpoint serving it
would be one Jellyfin does not have, and an extension a client can discover is still a delta
(Principle I).

**A run that dies still writes its report.** The report is the deliverable, so losing one already
made is the failure this program must not have — and on the first complete sweep, 2026-09-03, it
had it: 64 comparisons were measured, the reference then died, and the roster teardown raised on a
`DELETE /Users` it could not answer, out of a context manager `main()` was standing outside of.
Nothing was written. A run now hands its findings out the moment they exist, and a failure after
that point becomes an **incident** on the report rather than the end of it: the document says
`THIS RUN DID NOT FINISH` before any table, every case the run never reached is listed with its
reason, and `is_clean()` is false for it. A failure *before* anything was measured — a seat that
could not be made, a server that could not be reached — is still `2` and still writes nothing,
because a report of nothing is the same overstatement pointing the other way.

**Exit codes:** `0` the run is clean, `1` the run is **not** clean — an untriaged difference, a
declared case it could not issue, a named comparison it did not run, a named comparison that
ran and measured something its own citation does not predict, or an incident — and `2` it could
not start. `1` is the ordinary answer: outstanding is not green, and the report says which of the
five it was.

Four supporting modules sit beside it, underscore-prefixed so CI does not try to start them:
`_differential.py` (the pure comparison engine), `_allowlist.py` (the allowlist, the named
comparisons and the request cases), `_reference.py` (the single-use reference instance below) and
`_probe.py` (the `.env` reader it borrows).

### The single-use reference instance

`_reference.py` stands up a Jellyfin **this project owns**, gives it this repository's own fixture
tree as its only library, waits for the scan on the server's own answer, and destroys it with
everything it wrote — on the success path and the exception path alike, and a run that finds the
wreckage of a killed one destroys that first. It exists because the fixture comparison needs a
library on the *other* server, adding a library is a write, and the only reachable Jellyfin was an
operator's own ([ADR-0007](../docs/decisions/0007-a-container-runtime-for-the-reference-instance.md)).

**It needs a container runtime — Docker or Podman — and it is the only thing here that does.** The
image is pinned by **digest** and never by tag, recorded in
[reference-target §1](../docs/compatibility/reference-target.md#1-the-pinned-version) and printed
in every report beside the Atrium sha. The runtime is invoked as a subprocess through its command
line, never as a library, so this directory keeps its standard-library-only rule.

`reference_instance.py` is the same lifecycle for a human: it stands one up and **leaves it
running**, so a difference the harness reported can be looked at by hand.

```bash
python3 tools/reference_instance.py --fixture-root /path/to/tree --library Movies:movies:Movies
python3 tools/reference_instance.py --fixture-root /path/to/tree --check   # and destroy it again
python3 tools/reference_instance.py --sweep                                # destroy the leftovers
```

Everything a run creates carries the label `net.atrium.reference=single-use` — the container and
both of its volumes — so `--sweep`, and the sweep every instance performs before starting its own,
can find what a killed run left. **A machine with no runtime loses nothing it had**: the sweep
against a reachable server still runs, and every case and named row that needed an instance is
reported *outstanding with the reason* rather than skipped.

### Moving the pinned version

`bump_reference_version.py` runs
[conformance.md's four steps](../docs/compatibility/conformance.md#when-the-reference-version-moves)
in order and **refuses to continue past a failure**: fetch the new document and validate the
surface, run the differential and the twenty named comparisons, re-run every probe and re-date the
documents they support, and only then write the pin. It is a sequencer, not a new mechanism — every
step is a program already in this directory — and the sequence is the product: *"a bump that skips
step 2 has not been done, it has been declared."*

```bash
python3 tools/bump_reference_version.py --to 10.11.12 --jellyfin http://the-new-reference:8096 \
    --atrium http://localhost:8096 --image jellyfin/jellyfin@sha256:<the new digest> --dry-run
```

**Whether step 2 runs is measured and never declared.** The reference is asked its own version and
compared with the behavioural row of
[reference-target §1](../docs/compatibility/reference-target.md#1-the-pinned-version): the same
version means only the *contract* row is moving, so step 2 has no input and is skipped with that
reason; a different one means the running reference changed, and then no flag skips it. A version
that cannot be read at all stops the command before step 1 — an unreadable server is not a
document-only move, and treating it as one is the single path that ends in a new pin over readings
nobody took. A `--jellyfin` that answers `Server: Atrium/…` is refused for the same reason.

**A changed reference and a dead container are different answers.** A probe's `1` is a
contradiction to triage, its `2` is *it could not look*, and its `3` is a leak (above); the pinned
image dies with `SIGILL` on some starts, which reaches the command as `2` and stops it saying
**nothing was measured** rather than *the reference changed*. What it does not distinguish is a
reference that died mid-run from one that was never there: both are re-run.

**Nothing is written until every step has passed**, and then the pin moves in all nine places it
lives — five files — or in none of them. `--dry-run` classifies the move, prints the plan and
writes nothing anywhere.

### Planned

| Script | Purpose | Arrives with |
|---|---|---|
| `probe_wire_format.py`, `probe_sort_vocabulary.py`, … | The **three** remaining prior-measurement debts in [reference-target.md](../docs/compatibility/reference-target.md). The two that needed a server this project may configure were paid on 2026-09-02 by `probe_public_users.py` and `probe_local_address.py`; of what is left, two need ten lines of `urllib` against any reachable server and one needs a library scanned **twice**, which is the instance's | Their owning features |

A runner that executes every probe and summarises **arrived on 2026-09-02**, as step 3 of
`bump_reference_version.py` below rather than as a program of its own: running every probe is one
step of a procedure and not an activity, and the sentence that used to stand here — *"deliberately
not here yet, it is part of the harness feature 010 specifies"* — was true until 010 T14.

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
