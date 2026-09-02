# Roadmap

## v1 — "a client cannot tell"

**The goal of v1 is one sentence:** an unmodified Jellyfin client points at Atrium, browses a
library of movies, series and music, and plays them, without knowing it is not talking to Jellyfin.

Everything below is either a step toward that sentence or explicitly out.

### In scope

| Area | What v1 delivers |
|---|---|
| **Media types** | Movies. Series → seasons → episodes. Music: artists, album artists, albums, tracks, playlists |
| **Library** | Multiple library roots per media type; filesystem scanning; incremental rescan; deterministic identifiers |
| **Identification** | Filename and folder parsing; `.nfo` sidecars; embedded tags (ID3, Vorbis, MP4); local artwork |
| **Metadata providers** | TMDB for movies and series; MusicBrainz for music; behind a provider interface with caching and field-level precedence |
| **Users** | Multiple accounts, password authentication, per-user policy, per-user library visibility |
| **User data** | Favourites, played/unplayed, play counts, resume positions, per-user and per-item |
| **Sessions** | Session tracking, capability registration, playback start/progress/stop reporting |
| **Images** | Primary, Backdrop, Thumb, Logo, Banner; on-the-fly resizing with a disk cache; content-hash tags |
| **Playback** | `PlaybackInfo` negotiation against a client `DeviceProfile`; direct play with full `Range` support; remuxing to a compatible container without re-encoding, delivered over HLS |
| **Transcoding** | Software re-encoding when neither direct play nor remux satisfies the profile: video and audio codec conversion, resolution / bitrate / channel ceilings, HLS delivery, throttling, and scratch space with a ceiling |
| **Subtitles** | Text subtitle tracks — embedded and sitting beside the media — announced in the HLS manifest, negotiated from the client's profile, converted and served as files. Not painted into frames |
| **Conformance** | The four-level harness in [compatibility/conformance.md](compatibility/conformance.md) |

**Transcoding entered v1 on 2026-08-27**, and it is the one scope decision in this document that was
reversed rather than refined. The reason it was out was cost, and the reason it is in is that
"cannot play this" is the one answer a media server is not allowed to give: every other v1 feature
degrades gracefully when it is wrong, and this one leaves the user staring at a file they own and
cannot watch. `SupportsTranscoding` therefore becomes *true* in v1, and every consequence of that
claim — throttling, session teardown, bounded scratch space — is owed in the same version, because
advertising a capability and failing at delivery time is worse than not having it
([008 §3.3](../specs/008-playback-negotiation-and-delivery/spec.md#33-the-decision)).

**It shipped on 2026-08-29**, across
[008](../specs/008-playback-negotiation-and-delivery/tasks.md)'s fourteen tasks, and every
consequence that paragraph names is in with it: one supervised encoder per play session with a
stop route, a ping timeout, a disconnect path and a shutdown sweep; throttling and produced-segment
deletion behind the reference's own operator switches, both off as shipped; and scratch space that
survives none of them. The **Subtitles** row above is the one v1 promise 008 did not deliver — it
was never 008's to deliver and had no owning feature until 011 was opened on the same day.

**Subtitles shipped on 2026-08-31**, across [011](../specs/011-subtitle-delivery/tasks.md)'s twelve
tasks: text tracks announced in the HLS manifest when the delivery address names the manifest
method, a delivery method resolved per stream from the client's profile, three routes serving the
cues whole and windowed, and subtitle files beside the media discovered by a scan and served like
any other track. The row's last sentence holds — they are still not painted into frames, which is
the exclusion below and the one subtitle row left in
[behaviours §5](compatibility/behaviours.md#5-accepted-gaps-in-v1).

**Playlists shipped on 2026-09-01**, across [009](../specs/009-playlists/tasks.md)'s fourteen
tasks, and they are the one thing in the **Media types** row above that a client *writes* rather
than reads: create, read, add, remove, reorder, rename and delete. That makes them the only
structural state in v1 that does not come from the filesystem, and therefore the only thing in the
server's store that a rescan cannot rebuild — which is why 009's last criterion is about surviving
one ([009 §4](../specs/009-playlists/spec.md)). Six divergences ship with them, every one argued
and recorded ([behaviours §3.15–§3.19, §3.21](compatibility/behaviours.md)), and the sharpest is a
read the reference leaves open: naming another user in `userId` reads any private playlist there,
and is refused here.

### Out of scope, and why

| Not in v1 | Reason |
|---|---|
| **Hardware-accelerated transcoding** | VAAPI, QSV, NVENC, VideoToolbox: a per-machine hardware surface with its own detection, failure modes and driver matrix. v1 encodes on the CPU — slower, but portable and testable on any machine that can run the test suite |
| **Subtitle burn-in** | Needs a text-rendering stack (fonts, ASS positioning, shaping) and a second filter path. v1 delivers subtitle files — that half is **011**, which had no owning feature until 2026-08-29 and shipped on 2026-08-31 — but it does not paint them into frames. 011 measured what that costs and it is not nothing: `Encode` is the reference's per-stream answer for **every** track no declared profile fits, so v1 says the word and produces the frames without the cues ([behaviours §5](compatibility/behaviours.md#5-accepted-gaps-in-v1)) |
| **Live TV, DVR, tuners** | A separate product with its own hardware surface |
| **The Jellyfin web UI** | Would add a large endpoint surface whose only consumer is a UI this project is not building |
| **Plugins** | .NET assembly loading; no Python analogue worth inventing |
| **SyncPlay, WebSocket push** | Needs a session model v1 does not have; clients poll |
| **DLNA server** | Outside the client-facing contract |
| **Books, photos, home videos** | Outside the stated media scope |
| **Emby dialect** | Atrium is Jellyfin-shaped. See [compatibility/reference-target.md §5](compatibility/reference-target.md#5-what-is-not-a-target) |

## Feature order

Each row is one directory under [`specs/`](../specs/). The order is a dependency order, not a
priority order: each feature is testable the moment it lands, and each unlocks the next.

| # | Feature | Delivers | Depends on |
|---|---|---|---|
| **001** | Server identity and discovery | An unauthenticated client can find the server and identify it as Jellyfin | — |
| **002** | Authentication, users and sessions | A client can log in, hold a token, and be recognised on later requests | 001 |
| **003** | Library configuration and scanning | Files on disk become items with stable identifiers | — |
| **004** | Metadata resolution | Items get titles, dates, people, genres and artwork, from local and online sources | 003 |
| **005** | Item query API | `/Items` and the by-name endpoints: filtering, sorting, pagination, `Fields` | 002, 004 |
| **006** | Images | Artwork delivery, resizing, cache, tags | 004, 005 |
| **007** | User data and playstate | Favourites, played, resume, playback reporting | 002, 005 |
| **008** | Playback negotiation and delivery | `PlaybackInfo`, direct play, remux, software transcoding, `Range` | 005, 007 |
| **009** | Playlists | Create, read, add, remove, reorder | 005 |
| **010** | Conformance harness | The L0–L3 machinery as a deliverable, not a by-product | all |
| **011** | Subtitle delivery | Text subtitle tracks announced, negotiated, and served — embedded and beside the media | 008 |
| **012** | Negotiation inputs | A negotiation answer a client can act on: a source nothing has opened, and a delivery protocol spelled a way the comparison does not match | 003, 008 |

**008 is one feature, not two.** Transcoding lives inside it rather than in a directory of its own,
because it is not a separate capability a client can ask for: it is the third branch of a single
decision, reached only when the first two fail. Splitting it would put one decision ladder in two
specifications and guarantee they drift.

**011 is a correction to this table, not an addition to v1's scope.** The exclusion row above
excludes subtitle *burn-in* and says in the same sentence that **v1 delivers subtitle files** —
a promise made before 001 was written, and one this table had no row for. 008 excluded subtitle
extraction, conversion and delivery as out of its own scope, correctly: it is a feature about
deciding a play method and moving the bytes of a media file. Nothing picked the promise up, so
between the two of them v1 as specified delivered **no** subtitle by any path, which is wider than
the burn-in row records and was found from the client's side rather than the server's
([client-atrium-tvos §4.2](compatibility/client-atrium-tvos.md#42-v1-has-no-way-to-deliver-a-subtitle-and-this-client-has-one-way-to-receive-one)).
011 is that row. Its number is 011 rather than a slot before 009 because numbers are assigned in
the order features are *started* and never reused ([specs/README.md](../specs/README.md)) — the
gap in the sequence is the information that this was found late, not planned late.

**011 is not everything the client traces found.** Both
[client-atrium-tvos §6](compatibility/client-atrium-tvos.md#6-where-these-findings-go) and
[client-embeat-mobile §7](compatibility/client-embeat-mobile.md#7-where-these-findings-go) route
their findings to *"the feature that comes after 010"*, and both are right that none of them is an
008 defect. 011 takes the two that are one mechanism — subtitle delivery end to end, which the
video client's own grouping calls *"the largest of them"*. The rest are handed on at the size those
documents measured them, and four of them are one probe away from being specifiable and none is
specifiable before its probe: a source with no stored inspection, two spellings of `hls`, a session
list that takes no `deviceId`, and an initialisation segment that restarts production. They become
a feature on the day their measurement session runs, and take their number then
([011 §2.1](../specs/011-subtitle-delivery/spec.md)).

**012 is that number, and it is two of the four rather than all of them.** Opened on 2026-08-29,
it applied the *"008 is one feature, not two"* test above to the handover itself and kept the two
that share a decision: `PlaybackInfo` has exactly two inputs, and v1 steps over one of them and
falls through the other, so both answer `200` with something a client cannot act on. The session
list's missing parameters go to **002**, which owns the route and owns the visibility rule they
narrow; the initialisation segment stays a
[behaviours §3.0](compatibility/behaviours.md#30-how-the-decision-is-made) defect decision, because
a feature is the wrong container for an argument about whether to keep reproducing something. Both
are measured at 012's gate and recorded where they belong
([012 §2.1](../specs/012-negotiation-inputs/spec.md)). Like 011, 012 opened with open questions and
no measurements of its own, and it adds no row to the surface — the first feature to change what an
already-listed route answers without adding one.

**010 is last in the list but not last in time.** L0 and L1 exist from 001 — the casing sweep has
to be in place before the first response model, or Principle I is enforced by discipline instead of
by CI. What 010 delivers as a feature is the *differential* layer, which needs a server complete
enough to compare.

**And the differential layer needed one thing this project did not have, which it now makes for
itself.** 010's spec was accepted on 2026-09-01 with its AC-2, which then read *"both servers,
pointed at the same built fixture, produce libraries with the same item count and the same
structure"* — recorded as
**blocked**, because the only Jellyfin this repository could reach was an operator's own server,
holding an operator's own library, on another machine: the fixture tree is not on its filesystem
and adding a library to it would be writing to data this project does not own. **Decided the same
day: a run that needs the fixture on both sides stands up a reference instance of its own** — the
pinned version, the repository's fixture tree as its only library, used for the comparison and then
destroyed with everything it wrote, including on failure. AC-2 is unblocked, 010 §7's OQ-5 is
answered, and with them every one of 010 §3.10's named comparisons that needs a planted file, a
multi-part film, a legacy-encoded subtitle or an empty library. What such an instance runs on is
[ADR-0007](decisions/0007-a-container-runtime-for-the-reference-instance.md), decided the same day.

**And then the instance was built, the comparison was taken, and AC-2 did not survive it.** 010's
fifteen tasks all ran on 2026-09-02. The instance stands up from a pinned digest, configures itself
over the reference's own first-time-setup operations with no human, scans the repository's fixture
tree as six typed libraries and dies with everything it wrote; the reading it produced is checked in
and Atrium's scan is compared against it in the default job with no Jellyfin anywhere. **The two
readings differ in forty-seven declared places** — a zero-byte film that is an item there and not
here, twenty-five files named two ways, twenty-one container rows — so the criterion's *"the same
item count and the same structure"* is false, and every one of the forty-seven belongs to 003 or 004
rather than to the harness, which [010 §2](../specs/010-conformance-harness/spec.md) puts outside
this feature entirely. **The criterion moved rather than the measurement**: amending AC-2 to state
the comparison it turned out to be was **D-7**, reserved for its owner by the closing task rather
than improvised by it, and **taken on 2026-09-02** — the reference's reading is recorded, Atrium's
scan of the same tree is compared against it in the default job, every difference is declared with
its reason and its owning feature, an undeclared difference fails, and a declared difference that
has gone away fails too. A status line that overstates the work is the one thing this feature exists
to prevent in others, which is why the flip waited for the decision and why the word is bounded:
**010 is `Implemented` on 2026-09-02** — fifteen of fifteen tasks, eighteen of eighteen criteria —
and that is not a claim that the harness has swept everything. Six of the twenty named comparisons
are outstanding with their owners, two of them because Atrium has no library-refresh route to make
them comparisons at all, and **no `level: L3` row has been shown to reach L3**: no complete sweep of
the 84 request cases against a real pair is recorded anywhere. Both are on 010's own owes list, and
the forty-seven differences stay 003's and 004's to decide.

**The second reason is the one that decides how the tooling is judged.** A disposable instance
takes every writing measurement off a server somebody uses. The convention says a probe that writes
removes what it made, including on failure, and on 2026-09-01 that was checked and did not hold:
009's runs had left **28 playlists** behind on the operator's server. Against an instance that is
destroyed either way, a leaked artefact costs nothing — which is the difference between a cleanup
that has to be perfect and one that only has to be tidy. Everything 010's gate did measure was
measured before any of this existed, against the real library, which is why each of those readings
is a named measurement and not a sweep.

### The first three, concretely

- **001** is small and unglamorous, and it is first because it is the first request every client
  makes and because it forces the wire-format decisions — PascalCase, date format, GUID shape —
  before anything else can encode them wrongly.
- **002** is where the four authentication mechanisms and the `X-Emby-Authorization` header get
  settled.
- **003** can proceed in parallel with 001 and 002: it has no HTTP surface of its own and is
  validated entirely against the fixture library.

## v2 — the management CLI

**One sentence:** everything an administrator does to an Atrium server can be done from a terminal,
against the same HTTP API a client uses, with no privileged side door.

Jellyfin's administrative surface is administered through its web UI. Atrium does not serve that UI
([reference-target.md §5](compatibility/reference-target.md#5-what-is-not-a-target)), so v1 leaves a
real gap: the server can be configured, but only by editing what is on disk. v2 closes it with a
command-line client.

**The constraint that makes this safe:** the CLI is a *client*. It speaks HTTP to the same endpoints
any other client could call, holds a token obtained the same way, and has no access to the database
or the configuration files that the API does not also give it. Anything the CLI can do, a Jellyfin
client could do too — which is exactly why it costs Principle I nothing: a tool that consumes the
API is not a dialect.

| In v2 | Out of v2 |
|---|---|
| Users: create, list, update policy, reset password | Anything requiring an endpoint Jellyfin does not have |
| Libraries: add, rename, remove, list, trigger a scan | Direct database access, direct config-file writes |
| Server configuration: read and update | A second authentication path for "local" callers |
| Sessions and playback: list, stop | Interactive full-screen UI — that is v3's problem |

**This grows the served surface, and that is the point.** The admin endpoints are Jellyfin's own —
`[spec: GetVirtualFolders, AddVirtualFolder, RemoveVirtualFolder, RenameVirtualFolder,
RefreshLibrary, CreateUserByName, UpdateUserPolicy, GetConfiguration, UpdateConfiguration]` — and
serving them is implementing more of Jellyfin, not inventing anything. The v1 endpoint set
([api-surface-v1.md](compatibility/api-surface-v1.md)) grows accordingly, under the same rule as
every other row in it: an endpoint enters the table with its provenance, or it does not enter.

> **Why this repository, and why now.** The same shape of problem — an administrative surface that
> needs a scriptable client — is waiting in other applications, and it is worth solving once with
> the answer written down. Atrium is where the experiment runs, because it is the case with the
> hardest constraint: the API cannot be bent to suit the tool. A CLI design that survives *"you may
> not add an endpoint for your own convenience"* is a design that transfers; one that quietly grows
> a helper route for every awkward operation teaches nothing. What v2 is expected to produce, beyond
> a working tool, is a recorded answer to how a CLI is structured against an API it does not own.

## v3 — the management UI

**One sentence:** the same administrative surface as v2, in a browser, for the operations that are
genuinely worse in a terminal.

Atrium's own management UI — not the official Jellyfin web UI, which stays out for the reason it has
always been out. It is a browser client of the endpoints v2 already brought into the server: users,
libraries, scans, configuration, sessions.

**The rule that decides every argument this feature will produce:** no endpoint exists for the sake
of the UI. If the UI wants something the Jellyfin API does not offer, the UI does without it. The
moment a route is added because a screen would be nicer with it, Atrium has a dialect and the
project has lost the thing it exists for (Principle I).

v3 follows v2 rather than replacing it: the CLI is the surface that gets exercised by scripts and
tests, and the UI is a second consumer of the same calls, which is the cheapest way to find out
whether v2's design was really API-shaped.

## Later, unscheduled

Not planned, not promised. Recorded so the shape of the ambition is visible:

- Hardware-accelerated transcoding, and subtitle burn-in.
- Subtitle search and download from providers.
- The official Jellyfin web UI.
- WebSocket push for library changes; trickplay generation; Postgres as an alternative store.

**Permanently out** — an Atrium-specific API dialect, in any form. Principle I.
