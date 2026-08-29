---
feature: 012-negotiation-inputs
title: Negotiation inputs
status: Draft
created: 2026-08-29
updated: 2026-08-29
depends_on: [003, 008]
---

# 012 — Negotiation inputs

> **This document describes WHAT and WHY only.** No technology names, no storage decisions.

## 1. Purpose

Make the negotiation answer only what it can deliver. `PlaybackInfo` has two inputs — what the
server knows about the file, and what the client said about itself — and on each of them v1 has a
branch the reference has not got: an input it cannot read is stepped over rather than refused, and
the answer that comes back names a capability with no address behind it.

**Client behaviour unlocked:** a title that starts. Today a client that is handed one of these
answers either dead-ends with nothing to fetch, or takes an address of a shape it did not ask for.

**This is not new scope.** Both cases are inside 008's accepted surface, on 008's own route, and
neither is an 008 defect: 008's code does what 008's documents say, and a specification silent
about a case is not one that is wrong about it
([client-atrium-tvos §6](../../docs/compatibility/client-atrium-tvos.md#6-where-these-findings-go)).
What is new is that the silence has been traced from the client's side, by two independent client
authors, and that the reference has been read at both points and does something different at both.

## 2. Scope

**In scope**

- What the negotiation answers for a media source the server has **never opened** — including
  whether it opens it then and there, what it answers if opening fails, and what the same item's
  library listing says about it.
- What the negotiation does with a **delivery protocol it does not recognise** in the client's
  profile: a spelling it did not expect, and a value that names no protocol at all.
- The consistency rule underneath both: **every capability the answer advertises has an address
  the client can fetch**, and every address it hands out is of the shape the answer says it is.

**Out of scope**

- **Everything the negotiation already decides.** The ladder, its order, its ceilings, its reasons
  and its refusals are [008 §3.3](../008-playback-negotiation-and-delivery/spec.md#33-the-decision)
  and are not reopened. This feature is about the two inputs reaching that ladder, not about the
  ladder.
- **Delivery.** No route serves anything new here; the four `stream` routes, `/universal`, the
  playlists and the segments are 008's and unchanged.
- **Subtitles**, which are [011](../011-subtitle-delivery/spec.md)'s, including the subtitle
  properties a negotiated source carries.
- **Narrowing the session list.** The reference declares three query parameters on `GET /Sessions`
  that v1 declares none of; §2.1 argues that they belong to the feature that owns the route, which
  is 002 and not this one. Measured here (OQ-7) because the measurement session is here; specified
  there.
- **The initialisation segment that restarts production.** A defect decision under the written
  procedure, not a requirement — §2.1, OQ-8.
- **Per-user preferences of any kind**, and anything that would make an answer depend on state v1
  does not keep.
- **Growing the surface.** No endpoint enters v1 here and no row of
  [surface.yaml](../../docs/compatibility/surface.yaml) changes: every behaviour in this document
  is a change to what an already-listed route answers.

### 2.1 Why this is one feature, and why two of the four findings are not in it

**This feature was assembled from a list, which is the failure mode it has to argue its way out
of.** [011 §2.1](../011-subtitle-delivery/spec.md) took two findings out of eleven that two client
traces had recorded, handed the rest on at the size their own documents measured them, and named
four of those as *"one probe away from being specifiable and none specifiable before its probe …
a feature whose first act is a measurement session, taking its number on the day that session
runs"*. This is that number and this is that day. But 011's own warning applies to its own
handover: **four findings do not become one feature by having been handed on together**, any more
than eleven became one by sharing a date.

The test is the [roadmap's *"008 is one feature, not two"*](../../docs/roadmap.md#feature-order)
paragraph read backwards, exactly as 011 read it: transcoding stays inside 008 because it is *the
third branch of one decision*, and splitting it *"would put one decision ladder in two
specifications and guarantee they drift"*. Applied to an assembly rather than a split: **a finding
belongs here only if what decides it is what decides the others.**

Answering that honestly costs this feature half its list.

| Finding | What decides it | Verdict |
|---|---|---|
| [tvOS §4.1](../../docs/compatibility/client-atrium-tvos.md#41-a-source-with-no-stored-inspection-is-the-clients-documented-dead-end) + [music §5.1](../../docs/compatibility/client-embeat-mobile.md#51-a-source-with-no-stored-inspection-loses-the-music-clients-whole-negotiation) — a source with no stored inspection | What the negotiation answers when the **file side** of its input is unreadable | **Here** |
| [tvOS §4.6](../../docs/compatibility/client-atrium-tvos.md#46-two-spellings-of-hls-and-only-one-of-them-selects-hls) — `"Hls"` does not select HLS where `"hls"` does | What the negotiation answers when the **client side** of its input is unreadable | **Here** |
| [tvOS §4.4](../../docs/compatibility/client-atrium-tvos.md#44-get-sessions-takes-no-deviceid-and-the-client-sends-one) — the session list takes no `deviceId` | Which sessions a caller may see, and how that set may be narrowed | **002's** |
| [tvOS §4.5](../../docs/compatibility/client-atrium-tvos.md#45-the-fmp4-init-segment-restarts-the-encoder-which-is-the-defect-the-client-pre-warms-to-dodge) — the initialisation segment restarts production | Whether a reproduced defect stays reproduced | **A defect decision, not a feature** |

**The two that stay are one decision seen from its two sides.** `PlaybackInfo` takes exactly two
inputs — a media source and a device profile
([008 §3.3](../008-playback-negotiation-and-delivery/spec.md#33-the-decision) opens with that
sentence) — and v1 has a lenient branch on each. A source with no stored inspection is stepped
over, so it keeps flags that were never decided and gets no address. A profile whose protocol is
spelled in a case the comparison does not match falls through to the other branch, so it gets an
address of the wrong shape. **Both produce a `200` a client believes and cannot act on**, and both
exist because v1 chose to carry on where the reference does not: the reference **opens the file**
`[source: Emby.Server.Implementations/Library/MediaSourceManager.cs:170-189 @ v10.11.11]` and
**binds the protocol to a two-member enumeration**
`[source: MediaBrowser.Model/Dlna/TranscodingProfile.cs:77 @ v10.11.11]`,
`[source: Jellyfin.Data/Enums/MediaStreamProtocol.cs @ v10.11.11]`. Neither of those is a
tolerance; each is a place where the reference has no third answer to give. Closing them is one
rule — *the negotiation answers nothing it cannot deliver* — and §2.2 is that rule stated
positively.

**The session list is 002's, and the opening reading of this feature had the wrong owner.** It was
put here as *"a route feature 007 owns"*; it is not. `GetSessions` carries `feature: "002"` in
[surface.yaml](../../docs/compatibility/surface.yaml), is specified in
[002 §3.8](../002-authentication-users-and-sessions/spec.md#38-sessions) with its own acceptance
criterion and its own conformance row, and the video client's trace says so in as many words —
*"it is not a missing route — the row is in `surface.yaml`, tagged `video-client`, implemented at
002"*. 007 added what a session **row carries** while it is playing
([007 §3.6](../007-user-data-and-playstate/spec.md)); it did not touch what a session **request may
ask for**. And the sentence the parameter narrows is 002's own — *"the sessions the caller may see:
their own always, and all of them for an administrator"* — so the interesting half of the question
is 002's too: whether the reference applies the filter before or after that visibility rule, which
is a question about who may see whose device and not a question about playback. It is also **three
parameters, not one**: the reference declares `controllableByUserId`, `deviceId` and
`activeWithinSeconds` `[source: Jellyfin.Api/Controllers/SessionController.cs:52-59 @ v10.11.11]`,
and the third of them interacts with the session reap
[007 §3.8](../007-user-data-and-playstate/spec.md) rather than with anything here. Measured at this
gate (OQ-7) because a measurement session is cheap to extend and expensive to convene; specified in
002, in the change that adds them.

**The initialisation segment is a decision, and a feature is the wrong container for one.** The
restart is faithful reproduction — the reference's first branch is *"starting transcoding because
fmp4 init file is being requested"*, taken before it has looked at what is running
`[source: Jellyfin.Api/Controllers/DynamicHlsController.cs:1501-1505 @ v10.11.11]` — and the video
client pre-warms its session to dodge it `[client-contract: 2026-08-29, §3]`. So the question is
not *what should this server do*, it is *should this server stop doing what the reference does*,
which is [behaviours §3.0](../../docs/compatibility/behaviours.md#30-how-the-decision-is-made) and
belongs in the behaviours document with an argument attached. Its input is a cost measurement,
which this gate can take (OQ-8), and its output is a `§3` entry, which this gate can write. Making
it an acceptance criterion here would smuggle a Principle V decision in as a requirement — the
mistake 011 refused to make twice, with its own two Principle I questions.

**Neither handover loses the work**, which is the whole point of writing the sizing down rather
than absorbing it: 011 handed the ordering finding to 005 with the test that answers it named, and
both of these are handed on with the probe that answers them named, in §7.

### 2.2 What is left, and why it is one thing

**One rule, stated positively: a negotiation answer is actionable.** Every capability it
advertises has an address behind it, and every address it hands out is of the shape the answer
says it is. The two findings are the two ways v1 breaks that rule, and they break it in the same
direction — by carrying on with an input the ladder cannot use, instead of resolving it or
refusing.

Read from the client's side, the two failures look nothing alike, and that is the argument rather
than an objection to it. The video client refuses direct play, looks for the address it was
promised, finds none and stops
([client-atrium-tvos §4.1](../../docs/compatibility/client-atrium-tvos.md#41-a-source-with-no-stored-inspection-is-the-clients-documented-dead-end));
the music client never asks, plays the bytes and quietly loses four features it computes off the
streams
([client-embeat-mobile §5.1](../../docs/compatibility/client-embeat-mobile.md#51-a-source-with-no-stored-inspection-loses-the-music-clients-whole-negotiation));
and the video client with a differently-cased profile takes an address that works, for a shape it
has designed itself out of
([client-atrium-tvos §4.6](../../docs/compatibility/client-atrium-tvos.md#46-two-spellings-of-hls-and-only-one-of-them-selects-hls)).
**Three symptoms, two lenient branches, one rule.** A feature defined by the rule catches all
three; a feature defined by any one symptom catches one and leaves the others to be found by the
next client author.

## 3. Behaviour

### 3.1 What a client sees today

Stated as the starting point, because every criterion below is a change to one of these. Each is
observable from a running server on `main` at 2026-08-29, and the file-level evidence for the
table lives in the two client traces rather than here
([client-atrium-tvos §4.1 and §4.6](../../docs/compatibility/client-atrium-tvos.md#4-the-eight-findings),
[client-embeat-mobile §5.1](../../docs/compatibility/client-embeat-mobile.md#51-a-source-with-no-stored-inspection-loses-the-music-clients-whole-negotiation)),
which is where a reader can check each one against merged code.

| What a client does | What it gets today |
|---|---|
| Negotiates an item nothing has ever opened | A source carrying `Id`, a `Container` inferred from its path and `Size`; `RunTimeTicks` absent, `Bitrate` absent, `MediaStreams` empty; `SupportsDirectPlay`, `SupportsDirectStream` and `SupportsTranscoding` all **`true`**; and **no `TranscodingUrl`** |
| Negotiates the same item again with direct play and direct stream both switched off | The same answer, unchanged, with the same three flags and still no address |
| Reads that item's media source from a library listing | The same empty shape, on every route that offers a source |
| Posts a profile whose transcoding entries name the protocol as `Hls` or `HLS` | A `TranscodingUrl` to the **progressive** delivery route, and `TranscodingSubProtocol` echoing the client's own spelling back — an answer that names one shape and addresses another |
| Posts a profile whose transcoding entries name a protocol that is neither spelling | The same progressive answer. Nothing is refused and nothing is reported |

The two rows in the middle are the load-bearing ones. The first says the failure is not
self-correcting: a client that comes back with the switches set to say *"I cannot direct-play
this"* is answered identically, because the branch that would have read the switches is the branch
that was skipped. The third says the shortfall is not confined to the negotiation, which is why
§3.2 has to decide what a **listing** answers as well as what a negotiation answers.

### 3.2 A media source the server has never opened

**The reference does not answer this question, because it does not let itself be asked it.** On a
negotiation it walks the item's sources and, when the first of them carries no video stream for a
video item or no audio stream for an audio item, it **refreshes the item with probing enabled and
then re-reads the sources** before any profile is applied
`[source: Emby.Server.Implementations/Library/MediaSourceManager.cs:170-189 @ v10.11.11]`,
`[source: Jellyfin.Api/Helpers/MediaInfoHelper.cs:87-110 @ v10.11.11]`. There is no branch after
that which skips a source: the per-source annotation runs on every source the response carries
`[source: Jellyfin.Api/Controllers/MediaInfoController.cs:189-215 @ v10.11.11]`. **v1 invented the
skip**, and it invented it because it had a state the reference resolves rather than describes.

**The library listing is the other half, and there the reference does not probe.** A listing that
asks for media sources reads them without the on-demand refresh
`[source: Emby.Server.Implementations/Dto/DtoService.cs:261 @ v10.11.11]`, so an item nothing has
opened plausibly reaches a listing empty on the reference too. If so, the music client's four
losses are **parity**, not a gap — and the tvOS symptom is the only one that is a gap. ⚠️
**UNVERIFIED**: nothing here has measured either half. OQ-1 and OQ-3.

**What v1 must decide, once the measurements are in**, and the candidates are not equivalent:

| Candidate | What a client sees | What it costs |
|---|---|---|
| Open the file during the negotiation, then answer normally | The reference's answer, whatever that turns out to be | A file read inside a request that has a client waiting on it |
| Answer the source with every capability flag `false` | The refusal 008 §3.3 rung 4 already specifies — no address, and a client that knows it | A source the server could have played is refused because nobody looked |
| Keep today's answer and record the gap | Unchanged | The two symptoms of §3.1, unchanged |

The first is the only candidate that is *parity*, and it is the only one whose cost is a decision
rather than a shortfall. It is not chosen here: a plan is not written against a draft spec, and the
choice turns on OQ-1, OQ-2 and OQ-9 together — whether the reference's refresh completes inside the
request, what it answers when the file will not open, and whether what it learns is **kept**, which
is what decides whether closing the video client's symptom also closes the music client's.

**When it happens** is not exotic. A file added since the last scan; a scan that ran before this
server could inspect anything; a file the inspection could not read; and — the widest of them — a
server on which nothing can inspect at all, where every item in every library is in this state at
once. The closing mechanism the accepted-gap record names today is *"a rescan"*
([behaviours §5](../../docs/compatibility/behaviours.md#5-accepted-gaps-in-v1)), which is true and
is not something a client can ask for; that row is this feature's starting point and its wording
moves when this feature lands.

**Whatever is decided, the flags stop being defaults.** The three capability flags are an *answer*
in the reference — computed per negotiation from the profile, with `SupportsDirectStream` mirroring
`SupportsDirectPlay` ([behaviours §2.22](../../docs/compatibility/behaviours.md#222-supportsdirectstream-mirrors-supportsdirectplay))
and `SupportsTranscoding` following the profile rather than the outcome
([008 T14](../008-playback-negotiation-and-delivery/tasks.md)). Today, on this path, all three are
whatever they were initialised to and nothing decided them. That is true regardless of which
candidate wins, and it is the one thing §5 can assert before the measurements land.

### 3.3 A delivery protocol the negotiation does not recognise

A client's profile says, per transcoding entry, how it wants a produced stream delivered. Two
spellings are meaningful to the reference and they are **lower-case by declaration**: the
enumeration's members are `http` and `hls`, spelled that way deliberately and carrying a comment
saying so `[source: Jellyfin.Data/Enums/MediaStreamProtocol.cs @ v10.11.11]`. The property is
bound to that enumeration rather than to free text, with `http` as its default
`[source: MediaBrowser.Model/Dlna/TranscodingProfile.cs:77 @ v10.11.11]`.

**Two consequences follow from it being an enumeration, and neither is measured.**

1. **A differently-cased spelling probably binds.** The reference's own general reading of a
   name onto an enumeration is case-insensitive, which would make `"Hls"` and `"HLS"` select HLS
   there and progressive here — a delta in the direction Principle I has least tolerance for,
   because the client is *correct* and this server is the one that misreads it. ⚠️ **UNVERIFIED**
   — read from the binding, not measured. OQ-4.
2. **A spelling that is neither probably does not bind at all.** Free text has a fall-through;
   an enumeration has a failure. A profile naming `"dash"`, or an empty string, may therefore be a
   refusal of the whole body rather than a silent demotion to progressive — which is the opposite
   of what this server answers, and of the same class as the lenience
   [behaviours §1.12](../../docs/compatibility/behaviours.md#112-an-unrecognised-query-value-is-ignored-not-rejected)
   records for a **query** value while 008 §3.2 records the opposite for a value inside this very
   body. ⚠️ **UNVERIFIED**. OQ-5.

**And the answer contradicts itself, which is a finding of its own.** When the comparison fails,
this server still writes the client's own spelling into the answer's `TranscodingSubProtocol`,
beside an address that is progressive. So the response says *"this is HLS"* and hands over a URL
that is not — one object stating one decision two ways, which is the shape
[007 T12](../007-user-data-and-playstate/tasks.md) found for an identity spelled two ways in one
body and is worse here, because a client can act on it. Whether the reference echoes the profile's
spelling or the enumeration's canonical one is OQ-6, and it is the difference between this being
one bug and two.

`/universal` does not have the problem, and the contrast is what makes it a defect rather than a
reading: the audio route normalises the same value before comparing it, under a note calling that
*"measured, not lenience"*
([client-atrium-tvos §4.6](../../docs/compatibility/client-atrium-tvos.md#46-two-spellings-of-hls-and-only-one-of-them-selects-hls)).
Two routes of this server read one value by two rules, and at most one of them can be parity.

### 3.4 Error paths

Every row here is a change to a path that answers `200` today, so the error table is short and
each row is a question rather than a rule. **None of it is specified until OQ-2 and OQ-5 are
measured**, and it is written out so that the measurement has a shape to fill:

| Condition | Status and body today | What decides it |
|---|---|---|
| Negotiating an item whose only file cannot be opened | `200`, a source with every capability advertised and no address | OQ-2 — the reference's answer when its own on-demand probe fails |
| Negotiating an item whose file has gone from disk since the scan | `200`, as above | OQ-2, same measurement, second case |
| A profile naming a delivery protocol that is neither spelling | `200`, a progressive address | OQ-5 — whether an unbindable value refuses the body |
| A profile naming a delivery protocol in an unexpected case | `200`, a progressive address and a contradicting `TranscodingSubProtocol` | OQ-4, OQ-6 |
| Every existing refusal on this route | Unchanged — [008 §3.2](../008-playback-negotiation-and-delivery/spec.md#32-post-itemsitemidplaybackinfo--getpostedplaybackinfo)'s table stands | — |

The last row is the important one: this feature adds no refusal that 008 does not already
specify, and if a measurement says otherwise that is a finding, not a licence to invent one.
[behaviours §3.0.2](../../docs/compatibility/behaviours.md#302-what-is-never-acceptable) forbids
inventing a third behaviour, and both rows above have exactly two candidates each.

## 4. Data the feature owns

| State | Observable as | Lifetime |
|---|---|---|
| Whether a file has been opened and what it holds | The stream properties, runtime and bitrate of a media source, on a listing and on a negotiation | Until the file changes |
| *(Possibly)* the result of an inspection taken during a negotiation | Whether the **next** listing of the same item carries what the negotiation learned | Decided by OQ-9 |

**No new state, and possibly no new state at all.** The first row is 003's and 008's, already
owned and already observable; this feature changes *when* it is written, not what it is. The
second row exists only if OQ-9 says the reference keeps what it learns on demand — and it is the
question that decides whether this feature has one symptom to close or two.

## 5. Acceptance criteria

**Provisional, and fewer than the feature will have.** Seven of the nine open questions block one
of these criteria, so what is written here is what holds under *every* candidate answer; a
criterion that depends on which candidate wins is not written yet. That is the same discipline
[011 §5](../011-subtitle-delivery/spec.md#5-acceptance-criteria) applied to its two parked
questions, in the other direction.

1. A negotiation for an item nothing has opened answers a source whose three capability flags were
   **decided** — by the profile and the ladder, exactly as they are for every other source — rather
   than left at whatever they were initialised to. Whether they come out `true` or `false` is
   OQ-1's to settle; that they were decided is not.
2. A negotiation whose answer advertises a capability the client cannot exercise directly carries
   an address for it. Stated as the invariant rather than as a branch: **no answer says a source is
   playable some way and offers nothing to play it from.** This is the criterion
   [client-atrium-tvos §4.1](../../docs/compatibility/client-atrium-tvos.md#41-a-source-with-no-stored-inspection-is-the-clients-documented-dead-end)
   asks for, in the form that survives whichever candidate §3.2 chooses.
3. Repeating that negotiation with direct play and direct stream switched off answers something
   **different** from the first answer — the property §3.1's second row shows is missing today, and
   the one a client relies on when it comes back for a second opinion.
4. A profile that names the delivery protocol in any case answers the same address, whatever
   §3.3's measurement says that address is; and the answer's stated sub-protocol and the shape of
   the address it hands over agree. Asserted as agreement rather than as a string, so it holds
   under both of OQ-6's answers.
5. A profile naming a protocol that is neither spelling answers what OQ-5 measured, on this route,
   for every one of an empty string, an unknown word and a numeric value.
6. Nothing in this feature changes what a negotiation answers for an item that **has** been
   opened, for any profile: the ladder, the reasons, the addresses and the flags of
   [008 §3.3](../008-playback-negotiation-and-delivery/spec.md#33-the-decision) are unchanged, and
   the existing conformance suite is the proof.
7. Nothing in this feature changes what a **listing** answers for an item that has been opened, on
   any of the routes that offer a media source.
8. The library listing and the negotiation agree about a never-opened item in whatever way OQ-3
   measured the reference agreeing about one — including if the measured answer is that they
   **disagree**, which is what the reference's two read paths suggest and which no criterion may
   quietly tidy up.

## 6. Conformance

| Endpoint | Level | How it is proven |
|---|---|---|
| `POST /Items/{itemId}/PlaybackInfo`, the never-opened source | **L3** | Golden per candidate class — a never-opened source with and without a profile, with the two switches on and off — plus differential against an item the reference has likewise never opened |
| `POST /Items/{itemId}/PlaybackInfo`, the profile's delivery protocol | **L3** | Golden per spelling class — the two canonical spellings, two altered cases, and three unbindable values — plus differential, which is the only thing that can settle a refusal against a fall-through |
| Media sources on the listing routes | **L2** | Fixture with one file the world has deliberately not opened, asserted on every route that offers a source |
| Error paths | **L2** | Table-driven over §3.4, per case, once §3.4 has statuses in it |

**L3 on both negotiation rows, and the reason is the same as 008's.** v1 requires L3 for the
playback paths ([conformance §1](../../docs/compatibility/conformance.md)), and these two are the
places where this server and the reference can agree on every field of a response and still send
a client somewhere different — which is exactly what a differential is for and what a golden test
cannot catch on its own.

**The fixture is the interesting part, and it is a subtraction.** 008's generated media are
inspected by the world that builds them; this feature needs one that is deliberately **not**,
which is a fixture that has to be built by leaving something out rather than by adding it.
[007's task gate](../007-user-data-and-playstate/tasks.md#what-the-gate-changed) and
[006's](../006-images/tasks.md#what-the-gate-changed) both found a criterion with no world to
prove it in; this is the same shape, noticed at the spec rather than at the task list, and it is
recorded here so the plan cannot forget it.

## 7. Open questions

**None of these has been measured.** This document opens the feature; it does not measure it, and
naming the probe that will answer each is what
[008's](../008-playback-negotiation-and-delivery/spec.md#7-open-questions) and
[011's](../011-subtitle-delivery/spec.md#7-open-questions-and-what-measuring-them-did) tables did
before their own gates. Every source line cited above was read at `v10.11.11` and **none of it has
been seen on the wire**; a reading predicts, it does not measure (Principle II), and 008's gate
overturned five claims that had been read correctly and framed wrongly.

OQ-1 through OQ-6 and OQ-9 each block something in this document. **OQ-7 and OQ-8 block nothing
here** and are recorded at the status §2.1 gives them, so they are neither lost nor mistaken for
this feature's failures.

| # | Question | Blocks | Resolved by |
|---|---|---|---|
| OQ-1 | Does a negotiation for an item the reference has never probed come back **fully annotated** — streams, runtime, bitrate, a decided set of flags and an address — because the request probed it on the spot? The source says it forces a refresh with probing when the first source has no stream of the item's own kind `[source: Emby.Server.Implementations/Library/MediaSourceManager.cs:170-189 @ v10.11.11]`, but whether that completes inside the request, and how long a client waits for it, is the whole feasibility question | §3.2, §5 AC-1, AC-2 | `tools/probe_uninspected_source.py` |
| OQ-2 | What does the reference answer when that on-demand probe **fails** — a file that is truncated, zero-length, unreadable, or gone from disk since the scan? This is the case with no third answer available: there is nothing to annotate and nothing to refresh, and §3.4's first two rows are empty until it is measured | §3.2, §3.4, §5 AC-2 | `tools/probe_uninspected_source.py` |
| OQ-3 | What does a **listing** answer for the same never-probed item — the same empty source this server sends, or something else? The listing path reads the sources without the refresh `[source: Emby.Server.Implementations/Dto/DtoService.cs:261 @ v10.11.11]`, which would make the music client's four losses parity rather than a gap and would cut this feature's client-visible half in two | §3.2, §5 AC-8; and the shape of [behaviours §5](../../docs/compatibility/behaviours.md#5-accepted-gaps-in-v1)'s row | `tools/probe_uninspected_source.py` |
| OQ-4 | Does a profile naming the delivery protocol as `Hls` or `HLS` select HLS on the reference? The property is an enumeration whose two members are lower-case by declaration `[source: Jellyfin.Data/Enums/MediaStreamProtocol.cs @ v10.11.11]`, `[source: MediaBrowser.Model/Dlna/TranscodingProfile.cs:77 @ v10.11.11]`, and how a name is matched onto it is a property of the reading, not of the enumeration — so it is unanswerable without one request | §3.3, §5 AC-4 | `tools/probe_playback_info.py`, extended |
| OQ-5 | What does the reference answer for a protocol value that names neither member — an empty string, an unknown word, a number? An enumeration binding fails where free text falls through, so the candidates are a refusal of the whole body and a silent demotion to progressive, and they are opposites. 008 §3.2 already measured an unrecognised token **inside this body** as a `400`, which is a lead and not this value | §3.3, §3.4, §5 AC-5 | `tools/probe_playback_info.py`, extended |
| OQ-6 | Does the reference's answer echo the **profile's** spelling of the protocol into `TranscodingSubProtocol`, or the enumeration's canonical one? It decides whether this server's contradiction — a sub-protocol naming HLS beside a progressive address — is one defect or two, and whether AC-4's agreement clause is a reproduction or a divergence | §3.3, §5 AC-4 | `tools/probe_playback_info.py`, extended |
| OQ-7 | **Not this feature's to act on — 002's** (§2.1). `GET /Sessions` declares `controllableByUserId`, `deviceId` and `activeWithinSeconds` `[source: Jellyfin.Api/Controllers/SessionController.cs:52-59 @ v10.11.11]` and v1 declares none. What does each narrow, does the filter run before or after the caller's visibility rule, and what does a non-administrator naming another device's id get back? The last is the half that is not a convenience: it is who may see whose device, which is 002's sentence | Nothing here. Recorded so it is not lost, and specified in 002 | `tools/probe_session_filters.py` |
| OQ-8 | **Not this feature's to act on — a defect decision** (§2.1). The initialisation segment restarts production, in the reference and here `[source: Jellyfin.Api/Controllers/DynamicHlsController.cs:1501-1505 @ v10.11.11]`. What is measurable is the **cost**: how much production a resumed playback throws away, whether a second request for an already-written initialisation segment restarts anything, and whether the restart kills an encoder that was already producing the right thing. That measurement is the input [behaviours §3.0](../../docs/compatibility/behaviours.md#30-how-the-decision-is-made) needs, and the output is a `§3` entry rather than a criterion here | Nothing here. Recorded so it is not lost, and decided in the behaviours document | `tools/probe_transcode_session.py`, extended |
| OQ-9 | Does the reference **keep** what an on-demand probe learns, so that the next listing of the same item carries it — or is it spent on the one answer? It decides whether closing the video client's symptom also closes the music client's, which §2.2 currently asserts as one rule with two faces and cannot prove | §3.2, §4, §5 AC-8 | `tools/probe_uninspected_source.py` |

### 7.1 What the opening reading of this feature corrected

Recorded because the corrections were made by opening files, which is the method
[003's gate](../003-library-configuration-and-scanning/tasks.md#what-the-gate-changed) named and
every gate since has paid for.

1. **The session list is 002's route, not 007's.** Argued in §2.1. The consequence is not
   cosmetic: had it been absorbed here as *"one parameter"*, this feature would have specified a
   visibility rule belonging to a feature that already has one, and the question that actually
   matters — a non-administrator naming somebody else's device — would have been asked by a
   document with no criterion to hang it on.
2. **It is three parameters, not one.**
3. **The reference has no un-inspected source to describe**, because the negotiation probes on
   demand. Both client traces frame this finding as *"decide what an un-inspected source
   advertises"*; the reading says the decision may instead be *"reproduce the on-demand
   inspection, or record the gap"*, which is a different decision with a different cost, and it is
   why OQ-1 asks about feasibility rather than about wording.
4. **The two client symptoms may not have one closing mechanism.** §2.1 of both traces calls it
   *"one root cause, two clients"*, which is true of the cause and unproven of the cure: the
   reference's on-demand probe is on the negotiation path, and the music client never negotiates.
   OQ-3 and OQ-9 are that doubt made measurable.
5. **The initialisation-segment claim is no longer third-party.** The video client's trace marks
   it a *"lead for a probe"* because it cites a line of Jellyfin this repository had not read. It
   has now been read, and it says what the contract said it says. What is still owed is the cost,
   not the existence — which is why OQ-8 asks a narrower question than the trace did.

### 7.2 The dependencies outside this document

1. **No surface change.** Nothing enters [surface.yaml](../../docs/compatibility/surface.yaml) and
   nothing leaves it. 003 and 010 add no row either, but they add no *behaviour* to a route; this is
   the first feature to change what an already-listed route answers without adding one, and it is
   worth stating rather than assuming: every behaviour here is a change to a listed route's answer,
   and if a measurement turns out to need a route, that is a finding and a scope decision, not an
   implementation detail (Principle VI).
2. **One accepted-gap row is this feature's starting point.** The never-opened-source row of
   [behaviours §5](../../docs/compatibility/behaviours.md#5-accepted-gaps-in-v1) was written at 008
   T14 and names its closing mechanism as *"a decision about what an un-inspected source should
   advertise, routed by both client traces to the feature after 010"*. That is this feature, and
   OQ-1 may replace the wording as well as the row: if the reference resolves the state rather than
   describing it, the gap is not *"what should it advertise"* at all.
3. **Two records are owed to documents this feature does not own**, and both are written by this
   feature's measurement gate rather than by its code: 002 gains the three session parameters
   (OQ-7), and the behaviours document gains the initialisation-segment decision (OQ-8). Recorded
   here so that handing them on is a commitment rather than an omission.
4. **The two client traces are a floor, not a ceiling**, and they say so: absence from one means
   *not measured*, never *not needed*. The video client's went stale in a day. Nothing in CI
   notices when they do.

## 8. References

- [docs/compatibility/client-atrium-tvos.md](../../docs/compatibility/client-atrium-tvos.md) — the
  video client traced against merged code: §4.1 and §4.6 are this feature, §4.4 is handed to 002
  and §4.5 is handed to the behaviours document, and §6 is the grouping table §2.1 re-reads
- [docs/compatibility/client-embeat-mobile.md](../../docs/compatibility/client-embeat-mobile.md) —
  the music client's counterpart: §5.1 is the second face of §3.2, and its four losses are what
  OQ-3 and OQ-9 decide the status of
- [011 §2.1](../011-subtitle-delivery/spec.md) — the handover this feature is the other side of,
  and the scoping test it applies to itself
- [008 §3.1, §3.2, §3.3](../008-playback-negotiation-and-delivery/spec.md) — the media source
  shape, the negotiation this feature is inside, and the ladder it does not reopen
- [002 §3.8](../002-authentication-users-and-sessions/spec.md#38-sessions) — the session list and the
  visibility rule OQ-7 is a narrowing of
- [003 §3.2, §3.8](../003-library-configuration-and-scanning/spec.md) — what a scan opens, and the
  change detection that decides when a file is opened again
- [docs/compatibility/behaviours.md §1.12, §2.21, §2.22, §3.0, §5](../../docs/compatibility/behaviours.md)
  — the lenient-value rule this feature has to distinguish itself from, the negotiation-inert
  permissions, the mirrored flag, the defect procedure, and the accepted gap that opens §3.2
- [docs/roadmap.md](../../docs/roadmap.md#feature-order) — the *"008 is one feature, not two"*
  paragraph, read backwards, and the feature-order table updated in the same change
- `[spec: GetPostedPlaybackInfo, GetSessions, MediaSourceInfo, MediaStream, DeviceProfile,
  TranscodingProfile, PlaybackInfoDto, PlaybackInfoResponse]`
- The reference's own paths, read at the opening and **not yet measured**:
  `[source: Emby.Server.Implementations/Library/MediaSourceManager.cs:170-215, 348 @ v10.11.11]`,
  `[source: Jellyfin.Api/Helpers/MediaInfoHelper.cs:87-117, 251-268 @ v10.11.11]`,
  `[source: Jellyfin.Api/Controllers/MediaInfoController.cs:119-215 @ v10.11.11]`,
  `[source: Emby.Server.Implementations/Dto/DtoService.cs:261 @ v10.11.11]`,
  `[source: MediaBrowser.Model/Dlna/TranscodingProfile.cs:77 @ v10.11.11]`,
  `[source: Jellyfin.Data/Enums/MediaStreamProtocol.cs @ v10.11.11]`,
  `[source: Jellyfin.Api/Controllers/SessionController.cs:44-70 @ v10.11.11]`,
  `[source: Jellyfin.Api/Controllers/DynamicHlsController.cs:1480-1530 @ v10.11.11]`
