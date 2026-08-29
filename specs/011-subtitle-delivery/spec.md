---
feature: 011-subtitle-delivery
title: Subtitle delivery
status: Draft
created: 2026-08-29
updated: 2026-08-29
depends_on: [003, 005, 008]
---

# 011 — Subtitle delivery

> **This document describes WHAT and WHY only.** No technology names, no storage decisions.

## 1. Purpose

Put a subtitle on the screen: announce the text subtitle tracks a file carries, let a client choose
one, and serve its text.

**Client behaviour unlocked:** subtitles. Today a user who turns them on sees nothing, on every
playback path that is not the file being read byte for byte off disk.

**This is a v1 promise being kept, not v1 growing.** The
[roadmap's own exclusion row](../../docs/roadmap.md#out-of-scope-and-why) excludes *subtitle
burn-in* and says, in the same sentence, that **v1 delivers subtitle files**. Nothing was ever
written that delivers one. The promise fell between two features rather than being descoped by
either: 008 §2 excludes *"subtitle extraction, conversion and delivery as a separate route"* — a
correct decision for a feature about deciding a play method and moving bytes — and the feature
order ran 001 to 010 with no row to catch what 008 put down. So the scope question this feature
answers is not *should v1 do this*, which the roadmap answered before 001 was written. It is
*which feature owns it*, and until this document the answer was none.

## 2. Scope

**In scope**

- The subtitle properties a media source's streams carry: which streams are **text** subtitles,
  whether a stream can be served on its own, how it would be delivered and from where.
- Choosing a delivery method for a chosen track from what the client's profile says it accepts,
  and honouring the track the client asked for — at negotiation and on a delivery request.
- Announcing text subtitle tracks in the **HLS master playlist**, when the client's profile asks
  for them.
- `GET /Videos/{itemId}/{mediaSourceId}/Subtitles/{index}/subtitles.m3u8` — `GetSubtitlePlaylist`.
- `GET /Videos/{itemId}/{mediaSourceId}/Subtitles/{index}/Stream.{format}` — `GetSubtitle`, whole
  file and windowed.
- Extracting a text subtitle track from its container and converting it to the format the client
  asked for.
- **Subtitle files sitting beside the media**: seeing them at all, counting them, offering them as
  streams, and serving them.

**Out of scope**

- **Subtitle burn-in.** Unchanged, and for the reason the roadmap gives: a text-rendering stack and
  a second filter path. This feature is the other half of that row, not a reopening of it.
- **Image subtitles as text.** A bitmap track cannot become a cue list without optical character
  recognition. It is announced as a stream like any other and never announced in a manifest;
  §3.4.
- **Subtitle search and download from providers**, and everything under
  `/Providers/Subtitles/…`. The roadmap lists it under *later, unscheduled*.
- **Uploading or deleting a subtitle** — `POST` and `DELETE /Videos/{itemId}/Subtitles/{index}`.
  No analysed client calls either, and v1 writes nothing into a library root (004 §2).
- **Per-user subtitle preferences** — a default language, a "forced only" mode, a remembered
  choice. 008 §3.1 records `DefaultSubtitleStreamIndex` as exactly this and v1 does not keep it;
  a client sends the index it wants on each request.
- **Every other finding the two client traces record**, from a source with no stored inspection to
  UDP discovery. §2.1 says where each goes, and why none of them is decided by what decides a
  subtitle.
- Trickplay, and live streams.

### 2.1 Why this is one feature, and why the gaps beside it are not in it

**Both client documents hand this scoping decision here, and neither takes it.** The trace of the
video client closes with *"they are not 008 defects, and they are not amendments to it — 008 closes
on its accepted scope; every finding above was measured against code that does what its spec, plan
and tasks say it does"*, and routes its findings to *"the next one after 010"*
([client-atrium-tvos §6](../../docs/compatibility/client-atrium-tvos.md#6-where-these-findings-go));
the music client's trace says the same in its own words and calls them *"input to the feature that
comes after 010"*
([client-embeat-mobile §7](../../docs/compatibility/client-embeat-mobile.md#7-where-these-findings-go)).
That feature is this one, so the first thing to say is that **an earlier draft of this section was
wrong**: it recorded four of these as *amendments owed to 008, 007 and 002*, and they are not.
008's code does what 008's documents say. A specification that is silent about a case is not a
specification that is wrong about it, and calling a silence an amendment blames a document for a
question nobody put to it.

**But "input to the feature after 010" is a destination, not a scope**, and both documents show
it: each closes with a *grouping table* whose rows are visibly different shapes of work — one a
009 scope decision, one an amendment to 001, one a sentence of prose in behaviours, one a test
that *"can be written today"*. Two documents' worth of findings do not become one feature by
sharing a date. So the scoping is the work this section does, and the test it uses is the
[roadmap's *"008 is one feature, not two"*](../../docs/roadmap.md#feature-order) paragraph read in
the other direction.

That paragraph keeps transcoding inside 008 because it is **the third branch of one decision**, and
splitting it *"would put one decision ladder in two specifications and guarantee they drift"*.
Applied to a feature being *assembled* rather than split, it says: a finding belongs here only if
what decides it is what decides subtitles. Bundling by *when a gap was found* rather than by *what
decides it* turns a specification into a changelog, and produces the same drift from the other
direction — several mechanisms, each described in two documents.

**On that test, exactly two findings are this feature**, and the video client's own grouping table
had already put them together and sized them: *"§4.2 + §4.3 — subtitle delivery, end to end. The
largest of them, and §4.3 is a line inside it rather than work of its own."* §4.3's own closing
sentence is blunter still — *"whoever does §4.2 owns this line"* — and it is AC-4 here.

**Everything else is handed on**, to the shape the client documents themselves measured it as:

| Finding | Shape of the work, as its own document sizes it | Not here because |
|---|---|---|
| [tvOS §4.1](../../docs/compatibility/client-atrium-tvos.md#41-a-source-with-no-stored-inspection-is-the-clients-documented-dead-end) + [music §5.1](../../docs/compatibility/client-embeat-mobile.md#51-a-source-with-no-stored-inspection-loses-the-music-clients-whole-negotiation) — a source with no stored inspection advertises direct play and offers no address | One branch, one criterion, one accepted-gap entry. *"Shared with the tvOS client's §4.1 and worth doing once"* | It is a decision about what the **negotiation ladder** answers with nothing to negotiate against. One skipped branch, two clients, two failures that look nothing alike — and none of them is a subtitle |
| [tvOS §4.6](../../docs/compatibility/client-atrium-tvos.md#46-two-spellings-of-hls-and-only-one-of-them-selects-hls) — `"Hls"` does not select HLS where `"hls"` does | *"One probe each, then one parameter each. Both are cheap and neither is safe to guess"* | It is the **delivery address's** vocabulary, and it is unanswerable before the probe that says whether the reference is case-insensitive there |
| [tvOS §4.4](../../docs/compatibility/client-atrium-tvos.md#44-get-sessions-takes-no-deviceid-and-the-client-sends-one) — the session list takes no `deviceId` | Same row of the same table | It is the **session list's** request shape. The client already matches on what is playing, so this is a degradation whose worst case is an administrator reading another device's row |
| [tvOS §4.5](../../docs/compatibility/client-atrium-tvos.md#45-the-fmp4-init-segment-restarts-the-encoder-which-is-the-defect-the-client-pre-warms-to-dodge) — the initialisation segment restarts production | *"A [behaviours §3.0](../../docs/compatibility/behaviours.md#30-how-the-decision-is-made) decision, taken on a probe, before any code"* | It is a **defect decision**, not a requirement. The restart is faithful reproduction, the client pre-warms to dodge it `[client-contract: 2026-08-29, §3]`, and the Jellyfin-side claim behind it is a third-party lead this repository has not measured. A feature is the wrong container for an argument |
| [music §5.3](../../docs/compatibility/client-embeat-mobile.md#53-a-piped-mp3-carries-no-xing-frame-which-is-not-the-blank-one-the-client-measured), [§5.4](../../docs/compatibility/client-embeat-mobile.md#54-every-universal-request-re-encodes-for-a-different-reason-than-the-reference-does), [§6.1](../../docs/compatibility/client-embeat-mobile.md#61-an-honest-content-length-on-a-capped-transcode), [§6.2](../../docs/compatibility/client-embeat-mobile.md#62-keying-a-transcode-on-a-client-supplied-playsessionid) | *"One question about where a progressive re-encode is produced, asked three ways. Settle it once"* | It is one question about **where a progressive re-encode is produced**. Two of its four parts are Principle I improvements rather than parity — recorded in §7 as OQ-9 and OQ-10 so they are not lost, and owned there rather than here |
| [music §5.8](../../docs/compatibility/client-embeat-mobile.md#58-the-album-play-queue-is-correctly-ordered-by-accident) — the album play queue is ordered by accident | *"One test, and it can be written today. The only item here that needs no decision"* | See below |
| [tvOS §4.7](../../docs/compatibility/client-atrium-tvos.md#47-udp-discovery-is-out-of-v1-and-the-client-needs-it) — UDP discovery | *"An amendment to 001, or its own small feature. Not a route"* | It is not an endpoint and not a subtitle |

**The ordering finding is 005's, and its own document says the cheap answer is a test.** The music
client requests its album queue as `SortBy=ParentIndexNumber,IndexNumber,SortName` and its year
sort as `ProductionYear,PremiereDate,SortName`; three of those keys are outside v1's eight-member
vocabulary and an unrecognised token is **dropped, not refused**
([behaviours §1.12](../../docs/compatibility/behaviours.md#112-an-unrecognised-query-value-is-ignored-not-rejected),
005 §3.3), so two thirds of the first request evaporates and the album queue is ordered by
`SortName` alone. It comes out **right**, because an audio sort name is a zero-padded disc and
track ahead of the raw name
([behaviours §2.6](../../docs/compatibility/behaviours.md#26-sortname-has-two-derivations-and-three-types-use-the-second)),
so sorting by it sorts by disc then track then name — the order the dropped keys asked for, reached
from the other end. **The finding is that nothing states the dependency**, and the answer is one
test asserting a multi-disc album's order under that exact `sortBy` string, which belongs beside
[005 §3.4](../005-item-query-api/spec.md). Adding the three keys is the expensive answer and
probably the wrong one — a key no reference server orders by is a delta — and what decides it is a
debt already recorded:
[behaviours §2.5](../../docs/compatibility/behaviours.md#25-sortby-vocabulary)'s eight members rest
on a `[prior-probe: Jellyfin 10.11.11, 2026-06-13]` nobody has re-run, while the reference's own
enumeration has thirty members `[source: Jellyfin.Data/Enums/ItemSortBy.cs @ v10.11.11]`. A client
sending three keys outside the eight is the first evidence the debt is worth paying.

**What the handed-on findings are not is homeless.** Four of them are one probe away from being
specifiable and none of them can be specified before its probe, which is a feature whose first act
is a measurement session — and by the convention that numbers are assigned in the order features
are *started* ([specs/README.md](../README.md)), it takes its own number on the day that session
runs. Recording them here with their sizing, rather than absorbing them, is what keeps that
possible.

### 2.2 What is left, and why it is one thing

Subtitles are one mechanism seen from five places, which is the positive half of the same argument.
A subtitle a client can watch requires, in order: a stream the source says is text; a delivery
method negotiated from the profile; a line in the manifest; an address that line points at; and
bytes at that address. **Remove any one and the other four deliver nothing** — which is precisely
how v1 arrived at zero subtitles from exclusions that were each defensible alone
([client-atrium-tvos §4.2](../../docs/compatibility/client-atrium-tvos.md#42-v1-has-no-way-to-deliver-a-subtitle-and-this-client-has-one-way-to-receive-one)).
The video client's own trace reaches the same conclusion from its side, listing the work in
dependency order — *"emit `IsTextSubtitleStream`; bind `EnableSubtitlesInManifest`; extract and
serve WebVTT; announce the tracks"* — and closing it with *"the first two are cheap and buy nothing
alone"*. That sentence is what makes this one feature rather than four cheap tickets. It is one
decision ladder, which is the test the roadmap paragraph sets.

## 3. Behaviour

### 3.1 What a client sees today

Stated as the starting point, because every criterion below is a change to one of these. Each is
observable from a running server on `main` at 2026-08-29, and each is traced against merged code by
[client-atrium-tvos §4.2 and §4.3](../../docs/compatibility/client-atrium-tvos.md#42-v1-has-no-way-to-deliver-a-subtitle-and-this-client-has-one-way-to-receive-one),
which is where the file-level evidence for this table lives:

| What a client does | What it gets today |
|---|---|
| Reads an item's `MediaStreams` or a source's | Subtitle streams, with codec, language and the default and forced flags — and **no property saying which of them are text**, and none saying how one would be delivered |
| Posts a profile declaring how it accepts subtitles | Accepted, and the subtitle part of it discarded on arrival |
| Posts `SubtitleStreamIndex` with a negotiation | Accepted, and never read |
| Fetches the HLS master playlist | One variant line and no media tags of any kind |
| Fetches any subtitle address | Nothing. No route in the surface accepts one |
| Puts an `.srt` beside a film and rescans | Nothing. No scan sees the file, so nothing counts it |
| Sends a subtitle track selection on a delivery request | Ignored. The delivery routes read an audio track selection and no subtitle one — *"today this costs nothing"*, because there is no subtitle on the HLS path to select, and *"it stops costing nothing the moment §4.2 is closed"* |

The result is the table that document already draws: subtitles work on an on-device remux, because
the tracks are inside the file the client is reading byte for byte, and **nowhere else** — not over
server HLS, remuxed or transcoded, and not from a file beside the media by any path.

### 3.2 Which streams are subtitles, and which of those are text

Every subtitle stream a source carries gains the four properties 008 §3.1 named as owed and did not
emit: whether it is a **text** subtitle, whether it can be served on its own, **how** it would be
delivered for this negotiation, and **where from**. `[spec: MediaStream]`

The text/image split is the one that decides everything downstream. A text track is a cue list and
can be converted, served alone and announced; an image track is a sequence of bitmaps and can be
none of those without burn-in, which is out (§2). The reference filters the manifest on exactly
this property `[source: Jellyfin.Api/Helpers/DynamicHlsHelper.cs:192-195 @ v10.11.11]`.

**The delivery-method property is an answer to a negotiation, not a fact about a file.** The same
track answers differently for two clients, and differently for the same client direct-playing and
transcoding — the reference resolves it separately on the direct-play branch and the transcode
branch of its own ladder
`[source: MediaBrowser.Model/Dlna/StreamBuilder.cs:771-773, 806-807 @ v10.11.11]`. It is therefore
a property of a *negotiated* source, and what a bare listing row carries is
**OQ-2**.

> ⚠️ **The names a manifest needs are names 008 decided not to emit.** The reference labels each
> announced track with the stream's `DisplayTitle`
> `[source: Jellyfin.Api/Helpers/DynamicHlsHelper.cs:604, 608 @ v10.11.11]`, and `DisplayTitle` is
> one of the six *localised* properties 008 §3.1 deliberately leaves absent, because an English
> approximation would differ from the reference on every track rather than be missing on it. A
> manifest cannot leave the name absent — it is a required attribute — so this feature must either
> reach the localisation 008 deferred or state what it writes instead. **OQ-4**, and it is the one
> place where this feature cannot inherit an accepted decision unchanged.

### 3.3 Choosing a track and a delivery method

Two inputs and one answer.

**The track.** A client either names one, or does not. A named index is honoured. With none named,
a default is chosen, and **the rule is not the one an audit of this feature first wrote down**: the
reference ranks the source's subtitle streams by a *score* it holds on each stream, takes the
highest, and consults the client's profile only to break a tie among equal top scores — falling
back to the source's own stated default when nothing separates them
`[source: MediaBrowser.Model/Dlna/StreamBuilder.cs:546-584 @ v10.11.11]`. "The profile picks the
default" is the tie-break mistaken for the rule. What that score is, and what v1 would have to
compute to reproduce the ranking, is **OQ-12**.

**The index is honoured in the negotiation *and* on a delivery request**, because a client changes
the subtitle track mid-playback by re-requesting delivery, not by re-negotiating: the video client
rewrites both track indices in the address it was handed rather than re-posting a negotiation
`[client-contract: 2026-08-29, §3]`. That override already works for audio and is dropped for
subtitles
([client-atrium-tvos §4.3](../../docs/compatibility/client-atrium-tvos.md#43-the-clients-track-override-works-for-audio-and-is-dropped-for-subtitles)),
which is why §4.3 costs nothing today and stops costing nothing the moment the manifest announces a
track — *"whoever does §4.2 owns this line"*. AC-4.

*The claim that the reference builds its delivery address from the source's default tracks and
ignores the indices posted with the negotiation — the reason the client overrides at all — is a
third-party claim about Jellyfin and a **lead, not a measured behaviour**. It is settled by the
probe 008 OQ-8 already names, and it does not change what this feature owes: honouring the index in
both places is safe whichever way it lands, because the client sends the same value twice.*

**The method.** The client's profile declares, per subtitle format, how it will take that format:
embedded in the container, as a separate file, as a separate stream in the manifest, burned in, or
dropped `[source: MediaBrowser.Model/Dlna/SubtitleDeliveryMethod.cs @ v10.11.11]`. The manifest
method applies only when the play method is transcode
`[source: MediaBrowser.Model/Dlna/StreamBuilder.cs:1549 @ v10.11.11]`, which is the mechanical
reason a direct-played file needs nothing from this feature and an HLS-delivered one needs all of
it.

**Burn-in is out, and it is the reference's fallback.** When no declared method fits, the reference
falls back to painting the track into the frames
`[source: MediaBrowser.Model/Dlna/StreamBuilder.cs:1517 @ v10.11.11]`. v1 cannot, so v1 must answer
something else on that branch, and every candidate answer is client-observable: dropping the track,
offering it as a separate file anyway, or refusing the negotiation. **OQ-5**, and it is the only
place in this feature where a divergence is certain rather than possible.

### 3.4 The manifest

When the negotiation selected a text subtitle track for manifest delivery, or the client's profile
asked for subtitles in the manifest, the master playlist gains **one media entry per text subtitle
stream**, and the variant line gains the group they belong to
`[source: Jellyfin.Api/Helpers/DynamicHlsHelper.cs:192-210, 338-350, 596-632 @ v10.11.11]`.

Each entry carries the track's name, whether it is the selected one, whether it is forced, its
language, and an address. The language falls back to a literal `Unknown` rather than being omitted,
same source.

**Image subtitle streams are never announced**, because the filter is on text (§3.2), and **a
burned-in selection suppresses the group entirely** — irrelevant in v1, where nothing burns in, and
stated so that the absence of the branch is a recorded consequence rather than an oversight.

**When nothing is selected and the profile asks for nothing, the master playlist is unchanged.**
This is the criterion that keeps 008's accepted answer intact: a client that says nothing about
subtitles must receive byte-identically what it receives today (AC-6).

**The address in a media entry is a playlist, not a file.** It names a per-track playlist relative
to the item and the media source, and that playlist's own entries name **windows** of the track —
each a start and an end position — rather than one whole file, same source. This is why
[client-atrium-tvos §4.2](../../docs/compatibility/client-atrium-tvos.md#42-v1-has-no-way-to-deliver-a-subtitle-and-this-client-has-one-way-to-receive-one)'s
argument and its conclusion are both right and are not in tension: *"adding `GetSubtitle` as a 56th
endpoint would not help this client"* is true — on the Jellyfin path the client never asks for it
directly — and the manifest is the only lever. But the lever pulls that route. **A manifest whose
entries point nowhere is not a smaller version of this feature; it is a worse failure than the
silence it replaces**, because a client that finds a track and cannot fetch it has already
committed its player to a track list. The route is not an alternative to the manifest, it is what
the manifest addresses.

### 3.5 Fetching a subtitle

Two addresses, and the second is reachable two ways.

**The per-track playlist** — `GetSubtitlePlaylist` — lists the windows of one track of one media
source, at a window length the caller states, covering the source's runtime.

**The track itself** — `GetSubtitle` — answers the track converted into the format named in the
address, whole or windowed. The windowed form is what the playlist's entries name; the whole-file
form is one the video client builds by hand `[client-contract: 2026-08-28, §4]`.

> **Two rows of one client document disagree about when that fallback fires, and which is right
> changes what the fetch route buys on its own.** The answer table of
> [client-atrium-tvos §2](../../docs/compatibility/client-atrium-tvos.md#2-the-answer) records the
> client requesting `…/Subtitles/{index}/Stream.vtt` ***when the manifest carries none***, while
> [§4.2](../../docs/compatibility/client-atrium-tvos.md#42-v1-has-no-way-to-deliver-a-subtitle-and-this-client-has-one-way-to-receive-one)
> says that path is wired for the other server flavour and *"the client will not compensate"*. If
> the first is right, serving this route alone already puts a subtitle on the screen; if the second
> is right, it buys nothing until the manifest announces one. **Only the client's author can
> settle it** — it is a claim about the client, not about the reference, so no probe here can reach
> it, and it is a question for the trace rather than for a measurement session. **It changes no
> scope**: the route is in either way, because the manifest addresses it (§3.4). What it changes is
> the *order* the work is worth doing in, and that belongs in the plan.

**These two routes do not share an authentication rule, in the reference's own declaration**: the
playlist route requires a caller and the track route declares no requirement at all
`[source: Jellyfin.Api/Controllers/SubtitleController.cs:208-212, 338-345 @ v10.11.11]` — which is
the same split 008 T6 measured across the delivery routes, and which
[behaviours §2.10](../../docs/compatibility/behaviours.md#210-the-image-and-delivery-routes-accept-a-token-and-require-none)
already describes for the routes it covers. Reading an attribute is not measuring a wire, so what
each route actually answers to a caller with no token, an unknown token and a query-string token is
**OQ-6**.

**Conversion is part of delivery, not a separate capability.** A client asks for a format by naming
it in the address; the stored track is in whatever format its container holds. If v1 served only
the formats it already has, a client asking for the one format it can render would be refused by a
server that holds the same cues in a different spelling.

### 3.6 Subtitles beside the media

A subtitle file next to the media is invisible to v1 today: nothing in a scan looks at it, so
nothing counts it, offers it, or serves it. 008 §3.1 already records one half of the consequence —
`HasSubtitles` counts only what is inside the container, so *"a film with an external `.srt` and no
embedded track answers nothing where the reference answers `true`"*
`[source: MediaBrowser.Providers/MediaInfo/FFProbeVideoInfo.cs:275 @ v10.11.11]`. That gap closes
here, and the rest of it with it: a discovered file becomes a subtitle stream on its source, marked
external, and is deliverable through §3.5 like an embedded one.

**Which files count as a subtitle for which item is a naming question**, and naming questions have
been the most expensive class in this repository (003, 004). Language suffixes, forced markers,
files in a subdirectory, and files whose stem matches an item only after the same cleaning 003
applies to a filename — each is a rule, and each is measurable against the reference before it is
written. **OQ-7.**

### 3.7 Error paths

Every one of these is what a client branches on, and none may be invented:

| Condition | Owed answer |
|---|---|
| Item unknown or not visible to the caller | Per the shape the owning route family uses — and the delivery routes split across shapes by *where* the refusal happens (008 §3.5, §3.6), so this is measured per route, not assumed. **OQ-8** |
| Media source names nothing on the item | Measured. 008 T8 found one route answering `400` where its siblings split `400`/`500` on the same malformed identifier |
| Index names no stream, or names a non-subtitle stream | Measured |
| Index names an **image** subtitle and a text format was asked for | Measured — the interesting case, because conversion is impossible rather than unsupported |
| Format in the address is one the server cannot produce | Measured |
| Window length absent or not positive on the playlist route | The reference raises on its own argument check, which is the shape behaviours §1.11 calls the controller refusal — to be confirmed on the wire |
| Source has no runtime, so windows cannot be laid | Same |

## 4. Data the feature owns

| State | Observable as | Lifetime |
|---|---|---|
| Which streams of a source are text subtitles | The stream properties of §3.2 | For as long as the file is inspected |
| Subtitle files found beside the media | Additional external subtitle streams on the source, and `HasSubtitles` | Until a rescan finds them gone |
| The converted text of a track | Only as the body of a fetch | Not observable as state; a repeat fetch answers the same cues |

**No per-user state.** A subtitle choice is carried on the request that needs it and is not
remembered, which is the same line 008 draws for `DefaultSubtitleStreamIndex` and §2 restates.

## 5. Acceptance criteria

1. Every subtitle stream of an item and of a media source carries the four properties of §3.2, and
   a text track and an image track differ in the first of them.
2. A negotiation carrying a subtitle index answers a source whose selected subtitle track is the
   one named; a negotiation carrying none answers the default §3.3's ranking picks, and a
   discriminating case proves the profile breaks a tie rather than making the choice — two tracks
   the ranking separates are not reordered by a profile that prefers the loser.
3. A profile that declares no subtitle handling negotiates exactly as it does today — the
   response is unchanged from the accepted 008 answer for the same request.
4. A **delivery** request carrying a subtitle index is served with that track — the criterion
   [client-atrium-tvos §4.3](../../docs/compatibility/client-atrium-tvos.md#43-the-clients-track-override-works-for-audio-and-is-dropped-for-subtitles)
   asks for, in its subtitle half. *(Its audio half was owed to 008 and **008 T14 paid it**: the
   parameter had only ever been asserted as a string in a negotiated address, and the assertion
   that it changes the audio that comes back is now
   `tests/conformance/test_progressive_delivery.py`'s. Without both halves the video client's
   "change the track" path breaks against Atrium and no test here fails, so this criterion is the
   remaining one.)*
5. A master playlist for a source with at least one text subtitle stream, negotiated for a profile
   that asks for subtitles in the manifest, carries one media entry per text subtitle stream and a
   variant line naming their group.
6. A master playlist for a profile that asks for nothing about subtitles is **byte-identical** to
   the one the same request answers today.
7. An image subtitle stream never appears in a master playlist, whatever the profile asks for.
8. The address of every media entry in a master playlist is fetched successfully by following it
   as written, and every entry of the playlist it answers is fetched successfully the same way.
   *(Written as a traversal rather than as a string comparison: the failure this feature exists to
   prevent is an announcement that leads nowhere — §3.4.)*
9. A whole-file fetch of a text track answers its cues, in the requested format, with timings that
   match the source's.
10. A windowed fetch answers the cues of that window and no others, and the concatenation of every
    window of a track is the whole track.
11. A subtitle file placed beside a media file and then scanned becomes an external subtitle
    stream on that item's source, is counted by `HasSubtitles`, and is fetchable through the same
    two routes as an embedded one.
12. Removing that file and rescanning removes the stream, and neither the item nor its user data
    is affected.
13. Each row of §3.7 answers the status and body measured for it, per route.
14. A subtitle fetched twice answers the same bytes.
15. Nothing in this feature changes what a **direct-played** file answers: the negotiation, the
    source list and the delivery of a file the client reads byte for byte are unchanged.

**Two things the music client asks for are deliberately not criteria here**, and are open questions
instead: an honest `Content-Length` on a capped transcode, and keying a transcode on a
client-supplied play-session identifier. Both are **improvements over the reference rather than
parity**, both are settled by measurement before they are argued, and neither belongs to this
feature at all (OQ-9, OQ-10; §2.1 hands them to the question they are three-quarters of). A
criterion asserting either would make this feature fail for being *more correct* than the thing it
reproduces — Principle I read backwards — and reading them as failures is the mistake their own
document was written to prevent: *"neither is a failure"*.

## 6. Conformance

| Endpoint | Level | How it is proven |
|---|---|---|
| The subtitle stream properties on an item and a source | **L3** | Golden per stream kind, plus differential — the properties appear on every source that has a subtitle, so an error is everywhere |
| `POST /Items/{itemId}/PlaybackInfo`, subtitle half | **L3** | Golden per profile class — declared method × text/image × named index or not — plus differential |
| `GET /Videos/{itemId}/master.m3u8`, subtitle half | **L3** | Golden manifest per profile class, including the unchanged one (AC-6), plus differential |
| `GET …/Subtitles/{index}/subtitles.m3u8` | **L2** | Playlist shape, window coverage, and the traversal of AC-8 |
| `GET …/Subtitles/{index}/Stream.{format}` | **L2** | Cue-level assertions against a fixture of known cues, whole and windowed, plus determinism (AC-14) |
| Subtitle files beside the media | **L2** | Fixture mutated between assertions (AC-11, AC-12) |
| Error paths | **L2** | Table-driven per route over §3.7 |

**Converted text is asserted cue by cue, not byte by byte against the reference.** Two converters
given the same cue list agree on the cues and disagree on whitespace, ordering of optional
attributes, and how they round a timestamp — differences no player sees. What is asserted is the
property a client depends on: *the cues, their text and their timings are the source's*. A byte
comparison here would be asserting that Atrium ships the reference's converter, which is not a
compatibility claim — the same argument 008 §6 makes for transcoded bytes.

**Fixtures are synthetic**, extending 008's: the existing generated media gain an embedded text
subtitle track of known cues, an embedded image subtitle track, and a sidecar file beside one of
them. No copyrighted media, and the cue list is small enough to assert in full.

## 7. Open questions

**None of these has been measured.** This document opens the feature; it does not measure it, and
naming the probe that will answer each is what 008's table did before its own gate. OQ-1 through
OQ-8 and OQ-11 and OQ-12 each block the plan and are each answered by a measurement rather than by
a decision — except OQ-4 and OQ-5, which are a measurement *and then* a decision this repository
takes. **OQ-9 and OQ-10 block nothing here**: they are recorded at the status §5 gives them so that
they are not lost and not mistaken for failures.

| # | Question | Blocks | Resolved by |
|---|---|---|---|
| OQ-1 | Does the reference announce subtitles when the profile asks for it in the manifest but the play method is direct play, or only on a transcode? The source reads as transcode-only for the manifest method, and the manifest also fires on the profile flag alone — the two conditions are joined by an *or* `[source: Jellyfin.Api/Helpers/DynamicHlsHelper.cs:197 @ v10.11.11]`, so the direct-play case has no answer without measuring it | §3.3, §3.4, AC-5 | `tools/probe_subtitle_manifest.py` |
| OQ-2 | Do the four subtitle stream properties of §3.2 appear on a **bare listing** source, or only on a negotiated one? 008 §3.1 measured 31 properties on every listed source and named these four as absent for a different reason — because v1 delivers none — so which of them are negotiation answers is unmeasured | §3.2, AC-1 | `tools/probe_subtitle_negotiation.py` |
| OQ-3 | What exactly does a media entry carry — every attribute, in order, with the reference's spellings and its `Unknown` fallback — and what does the variant line become? A manifest is compared as text by nothing and as bytes by 010's differential | §3.4, AC-5, AC-6 | `tools/probe_subtitle_manifest.py` |
| OQ-4 | The name a manifest entry carries is the stream's localised display title, which 008 §3.1 deliberately does not emit. Measure what it reads for an English-configured server, and decide whether this feature reaches the localisation 008 deferred or writes something else and records the divergence | §3.2, §3.4 | `tools/probe_subtitle_manifest.py`, plus a decision this repository takes rather than measures |
| OQ-5 | What does a server that cannot burn in answer where the reference falls back to burn-in — drop the track, offer it as a separate file, or refuse? Every candidate is client-observable, and the reference's own answer is unavailable because it never has to give one | §3.3 | `tools/probe_subtitle_negotiation.py`, then a divergence argued under behaviours §3.0 |
| OQ-6 | What do the two fetch routes answer to a caller with no token, an unknown token, and a token in the query string? The reference's declarations differ between the two routes; 008 T6 found the declared and the measured answers differ on exactly this class | §3.5, §3.7, AC-13 | `tools/probe_subtitle_delivery.py` |
| OQ-7 | Which files beside a media file the reference treats as its subtitles: the stem-matching rule, language and forced suffixes, subdirectories, and what it records as the stream's language and flags | §3.6, AC-11 | `tools/probe_sidecar_subtitles.py` |
| OQ-8 | The status and body of each row of §3.7, per route. 008 found delivery-route refusals splitting across three error shapes by *where* the refusal happens, so this cannot be inherited | §3.7, AC-13 | `tools/probe_subtitle_delivery.py` |
| OQ-9 | **An improvement over the reference, not parity — and not this feature's to answer.** An honest `Content-Length` on a capped transcode, which is the whole reason the music client ships a local proxy ([client-embeat-mobile §6.1](../../docs/compatibility/client-embeat-mobile.md#61-an-honest-content-length-on-a-capped-transcode)). Behaviours §3.3 already diverges *where the size is knowable before the first byte*; this asks to extend it to a case where it is knowable only by producing the whole file first, which trades latency for a header. The client's own warning bounds it — *"an estimated length is worse than none"*, measured 50% long for lossless — so half-measures are ruled out before they are proposed. **Measured first, never an acceptance criterion, and never read as a failure** | Nothing here. Recorded so it is not lost, and owned by the *"where a progressive re-encode is produced"* question of §2.1 | A measurement session, then behaviours §3.0 |
| OQ-10 | **An improvement over the reference, not parity — and not this feature's to answer.** Keying a transcode on a client-supplied play-session identifier, so every reconnect and retry is a cache hit ([client-embeat-mobile §6.2](../../docs/compatibility/client-embeat-mobile.md#62-keying-a-transcode-on-a-client-supplied-playsessionid)). Its two halves have opposite answers: **declaring the parameter is a delta** — the reference has not got it there, and that is what Principle I forbids most plainly — while caching the chunked branch may be no delta at all, since a client cannot observe a response being faster. So the answer is likely neither the ask nor a refusal. **Same status: measured before it is decided, never a criterion** | Nothing here. Recorded so it is not lost, and owned by the same question as OQ-9 | `tools/probe_transcode_session.py`, extended |
| OQ-11 | Does a windowed fetch answer timestamps in the window's own frame or the source's, and what do the two timestamp switches in the address change? The playlist's own entries set both of them, which says they matter and not what they do | §3.5, AC-10 | `tools/probe_subtitle_delivery.py` |
| OQ-12 | What is the per-stream **score** the reference ranks subtitle streams by, and can v1 reproduce the ranking from what it inspects? Reading the source overturned this feature's own first reading of §3.3 — the profile breaks a tie, it does not choose — so the ranking is the rule and it is unmeasured | §3.3, AC-2 | `tools/probe_subtitle_negotiation.py` |

**Three dependencies outside this document, none of them a measurement.**

1. **The surface grows by two rows.** `GetSubtitlePlaylist` and `GetSubtitle` are not in the 55, and
   L0 forbids serving a route that is not listed — the video client's trace says so of `Stream.vtt`
   in as many words. Both need a row with their consumers, feature and conformance level before any
   code, by the procedure in [AGENTS.md](../../AGENTS.md), *adding an endpoint*. This is the one
   place this feature contradicts
   [client-atrium-tvos §7](../../docs/compatibility/client-atrium-tvos.md#7-what-this-document-does-not-do)'s
   *"it does not grow the surface"* — correctly: that sentence is about what the **trace** does, and
   it says in the same breath that the open decision *"is not answered by adding a route"*. Adding
   the routes is not the answer; it is what the answer needs underneath it (§3.4).
2. **One accepted-gap row was wrong, and correcting it is not the same as closing it.** The
   subtitle row of [behaviours §5](../../docs/compatibility/behaviours.md#5-accepted-gaps-in-v1)
   said subtitles are *"delivered as files"*; they are not delivered at all. Both client traces
   recorded the correction as owed and neither made it; **008 T14 made it**, in the change that
   marked 008 `Implemented`, and the row now names this feature as its closing mechanism. What
   is owed here is the work, not the wording — and the row is rewritten again the day it lands,
   because "delivered as files" will still not describe a manifest-announced track.
3. **The two client traces are a floor, not a ceiling**, and they say so: absence from one means
   *not measured*, never *not needed*. The video client's went stale in a day. Nothing in CI
   notices when they do.

## 8. References

- [docs/roadmap.md](../../docs/roadmap.md#out-of-scope-and-why) — *"v1 delivers subtitle files"*,
  the promise this feature keeps, and the feature-order table corrected in the same change
- [docs/compatibility/client-atrium-tvos.md](../../docs/compatibility/client-atrium-tvos.md) — the
  video client traced against merged code: §4.2 and §4.3 are this feature, §6 is the scoping
  handover §2.1 answers, and §4.1 and §4.4 through §4.7 are what §2.1 hands on
- [docs/compatibility/client-embeat-mobile.md](../../docs/compatibility/client-embeat-mobile.md) —
  the music client's counterpart: §5.8 is the ordering finding owed to 005, and §6.1 and §6.2 are
  OQ-9 and OQ-10 with the status this document keeps them at
- [008 §2, §3.1, §3.3, §3.5, §3.7](../008-playback-negotiation-and-delivery/spec.md) — the
  exclusion this feature reverses, the three stream families it emits, and the delivery rules it
  inherits unchanged
- [005 §3.4](../005-item-query-api/spec.md) — the sort vocabulary §2.1 hands back
- [003 §3.2, §3.7](../003-library-configuration-and-scanning/spec.md) — what a scan looks at, and
  the name cleaning a sidecar rule would have to match
- [docs/compatibility/behaviours.md §1.11, §2.10, §3.0, §3.3](../../docs/compatibility/behaviours.md)
  — the error shapes, the token rule on delivery routes, the defect procedure, and the sizing rule
- `[spec: GetSubtitle, GetSubtitlePlaylist, GetMasterHlsVideoPlaylist, GetPostedPlaybackInfo, MediaStream, MediaSourceInfo, DeviceProfile, SubtitleProfile, SubtitleDeliveryMethod, TranscodingProfile]`
- The reference's own paths, read at the opening and **not yet measured**:
  `[source: Jellyfin.Api/Helpers/DynamicHlsHelper.cs:192-210, 338-350, 596-632 @ v10.11.11]`,
  `[source: Jellyfin.Api/Controllers/SubtitleController.cs:208-212, 338-400 @ v10.11.11]`,
  `[source: MediaBrowser.Model/Dlna/StreamBuilder.cs:546-584, 654, 771-773, 806-807, 1442-1570 @ v10.11.11]`,
  `[source: MediaBrowser.Model/Dlna/SubtitleDeliveryMethod.cs, MediaBrowser.Model/Dlna/SubtitleProfile.cs @ v10.11.11]`,
  `[source: MediaBrowser.Model/Dlna/TranscodingProfile.cs:119, MediaBrowser.Model/Dlna/StreamInfo.cs:117, 1067-1070
  @ v10.11.11]`, `[source: MediaBrowser.Providers/MediaInfo/FFProbeVideoInfo.cs:275 @ v10.11.11]`
