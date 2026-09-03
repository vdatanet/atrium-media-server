# AGENTS.md

Guidance for anyone — human or agent — making changes in this repository.

## Read first, in this order

1. **[docs/constitution.md](docs/constitution.md)** — ten principles that override everything else,
   including this file.
2. The **`spec.md`** of the feature you are touching, under [specs/](specs/).
3. **[docs/compatibility/behaviours.md](docs/compatibility/behaviours.md)** — the measured
   behaviours you must reproduce, including the defects we reproduce on purpose.

## Where the project is

**Features 001 through 011 are implemented, and 012 is the only one left `Accepted` and unbuilt.**
**[008](specs/008-playback-negotiation-and-delivery/)
landed on 2026-08-29 across fourteen tasks**, spec, plan and tasks all accepted the same day and
every one of the fourteen finding something the documents had wrong. Playback is therefore in: the
negotiation, the four `stream` routes, `/universal`, the HLS playlists and segments, and a
supervised encoder per play session. **[011](specs/011-subtitle-delivery/) landed on 2026-08-31
across twelve tasks**, three days after its spec was accepted at its own measurement gate — twelve
open questions answered by five new probes, four of them overturned — and every one of the twelve
finding something the documents had wrong, which is why its spec carries nine amendments and not
one. Subtitles are therefore in: the two file facts on every stream, the negotiation's per-stream
delivery method, the manifest's `#EXT-X-MEDIA` block and the group on every variant, the three
delivery routes, and subtitle files sitting beside the media — discovered, numbered ahead of the
container's own streams, and served. Not burned in, which is
[the roadmap's exclusion row](docs/roadmap.md#out-of-scope-and-why) and the one subtitle gap left in
[behaviours §5](docs/compatibility/behaviours.md#5-accepted-gaps-in-v1).
**[012's spec was accepted on 2026-08-29](specs/012-negotiation-inputs/spec.md)**,
at a gate that answered its nine open questions with two new probes and two extended ones and
withdrew one of the two client findings it was built on. **[009](specs/009-playlists/) landed on 2026-09-01 across fourteen tasks**, its spec accepted at a
gate whose five probes answered its six open questions and killed thirteen claims — including the
one the feature was built on, that a playlist entry has an identifier of its own — and every one of
the fourteen tasks then finding something further, which is why its spec carries twelve amendments
and its plan nine. Playlists are therefore in, and they are the only thing a client **writes
structure** to: creation with its four `400` bodies from three layers, the read with its
`PlaylistItemId` and its own `404` shape, adding with every container expanding recursively,
removing, the move's thirty measured pairs, deletion and the administrator-only rename. Six
divergences ship with them ([behaviours §3.15–§3.19, §3.21](docs/compatibility/behaviours.md)) and
two accepted gaps (a playlist has no `Path`; a non-administrator cannot rename their own).
**[010's spec was accepted on 2026-09-01](specs/010-conformance-harness/spec.md)**, the same day
009 shipped and the last of its dependencies became implemented, at a gate whose four probes
answered its four open questions with none surviving unchanged — the path it proposed to join two
servers on is absent from every default list row, a recorded session replays faithfully and still
cannot be the gate, and its two non-deterministic endpoints are three. It also found two
differences against **implemented** 005, and **both were decided on 2026-09-01**: `Similar` is a
random draw rather than a ranking, and its `limit` answers `limit + 4` on a movie seed — Atrium
diverges on each, argued in [behaviours §3.23 and §3.24](docs/compatibility/behaviours.md) and
stated in [005 §3.7 and AC-12](specs/005-item-query-api/spec.md). The same day settled the one
question that gate left open: a run that needs the fixture on both servers **stands up a single-use
reference instance over it and destroys it**, so 010's AC-2 is no longer blocked — which also takes
the writing measurements off an operator's server, where 009's runs had left 28 playlists behind.
**010's plan was drafted and accepted on 2026-09-01**, so its task list is the next gate: the plan's bulk is the thing
that does not exist yet — a **single-use reference instance**, stood up from a pinned image over
this repository's own fixture, configured over the reference's first-time-setup operations with no
human, and destroyed with everything it wrote. It reserved **five decisions** for their owner
instead of taking them, and **all five were taken on 2026-09-01**, every recommendation accepted:
the reference instance gets a container runtime, with
[ADR-0007](docs/decisions/0007-a-container-runtime-for-the-reference-instance.md) and no CI job
allowed near it; the harness stays in `tools/` on the standard library and the 3.9 floor; **AC-6 is
refined and an accepted spec amended for it**, because as accepted it failed the very allowlist its
own document ships — an entry now cites a behaviours section or one of four derivation classes, and
the reference's random `ChildCount` finally has an entry of its own
([behaviours §3.25](docs/compatibility/behaviours.md)); the fixture world keeps its default and its
measurement **waits on the instance that does not exist yet**, since a library scan is a write and
the only reachable server is an operator's; and the ignored-parameter report gets its fourth column,
written to the data directory and never to a route. **Its task list was accepted on 2026-09-02 and
all fifteen tasks ran the same day** — the comparison engine, the allowlist and the two other
registers, the identities a run creates and destroys, the single-use reference instance, the fixture
composed into six typed libraries, the twenty named comparisons, the probe convention and the
version-bump command. **010 became `Implemented` on 2026-09-02, and not before its own closing task
had been answered.** T15 found the class that task exists for: **AC-11 had no test at all** — the plan mapped it to
*"CI, unchanged"*, a claim about a workflow file and a fixture with nothing asserting either, in the
one feature whose whole value is a second server; **AC-7 had a half with no test**, the citation a
probe prints, which is the mechanism Principle II rests on; and **AC-2 said what its own measurement
contradicts** — *"the same item count and the same structure"* against **forty-seven declared
differences**, every one of them 003's or 004's and so outside this feature by its own §2. Amending
AC-2 was **D-7**, reserved for its owner rather than improvised and **taken the same day**: the
criterion now states the comparison that exists and runs — the reference's reading recorded,
Atrium's scan of the same tree compared against it in the default job, every difference declared
with its reason and its owning feature, an undeclared difference failing and a declared one that has
gone away failing too. **What `Implemented` means there is fifteen of fifteen tasks and eighteen of
eighteen criteria, and nothing wider**: six of the twenty named comparisons are still outstanding
with their owners, no `level: L3` row has been shown to reach L3, and the forty-seven differences
are 003's and 004's to decide — all of it on
[010's owes list](specs/010-conformance-harness/tasks.md#what-this-feature-owes-the-next-ones)
rather than inside the status word. 010 also found two differences in **implemented** features, both left to their
owners: a seat with all three playback permissions denied negotiated `SupportsTranscoding: true`
here and `false` there (008's, behaviours §2.21 — **answered on 2026-09-02**, and the gate that was
missing was not the one the report named), and Atrium's `is_hidden` default answers a
different `/Users/Public` on a login screen (002's, behaviours §2.2). What each implemented feature leaves the ones after it is written at
the end of its own task list rather than here, so it cannot go stale:
[008's](specs/008-playback-negotiation-and-delivery/tasks.md#what-this-feature-owes-the-next-ones)
is the longest and 010 collects most of it, with
[011's](specs/011-subtitle-delivery/tasks.md#what-this-feature-owes-the-next-ones) and
[009's](specs/009-playlists/tasks.md#what-this-feature-owes-the-next-ones) beside it;
[007's](specs/007-user-data-and-playstate/tasks.md#what-this-feature-owes-the-next-ones),
[005's](specs/005-item-query-api/tasks.md#what-this-feature-owes-the-next-ones) and
[006's](specs/006-images/tasks.md#what-this-feature-owes-the-next-ones) stand beside it, with 004's
standing notes below.

**004 owes 005 four things**, written down in
[004's tasks](specs/004-metadata-resolution/tasks.md#what-this-feature-owes-the-next-ones) rather
than here so they cannot go stale: `name_folded` on every item it touched, the pattern-driven
indexes, `ImageTags` emittable from `item_images` alone, and the artist **credit** distinction —
`/Artists` versus `/Artists/AlbumArtists` is that column and nothing else.

**The state is in the files, not here**, so it cannot go stale:

| Question | Read |
|---|---|
| Which features have a spec, a plan, tasks? | [`specs/README.md`](specs/README.md) — the status table |
| Which tasks are done? | The feature's `tasks.md`. Finished ones are `[x]` and carry a **Done** note saying what the task got wrong |
| What is next? | The first unticked task in the lowest-numbered feature |

The **Done** notes are worth reading before starting the next task. Most of them record something
the task statement or the plan asserted that turned out to be false, and the same class of mistake
tends to recur.

## The working rhythm

One task, one branch, one pull request, reviewed and merged before the next begins.

```
git checkout main && git pull && git checkout -b feat/001-tNN-short-name
# … the task …
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
git commit && git push -u origin <branch> && gh pr create --base main
```

[CI](.github/workflows/ci.yml) runs that same gate on every pull request, plus the surface and
property-name checks, the suite on the oldest and newest supported Python, and the `tools/` scripts
on the 3.9 floor they promise to run on. **No job contacts a Jellyfin server**, and the suite fails
any test that opens a TCP connection — so a probe belongs in `tools/`, run by hand, never in the
suite.

**Never commit to `main`.** It has happened once in this project, caught only because opening the
pull request failed with *"No commits between main and …"*. Merge with `--delete-branch`: a stacked
pull request is only retargeted when its base branch is deleted, and three of them once merged into
each other instead of into `main` because the branches were kept.

Every gate is a real gate. A plan does not start until its spec is `Accepted`; tasks do not start
until the plan is; code does not start until the tasks are (Principle III).

## The habit that has produced every real finding

**Measure the reference before implementing anything, even when the task looks trivial.**

Every task since T4 has found something the specification had wrong, and none of them were found by
reasoning:

| Task | Looked like | Turned out |
|---|---|---|
| T11 | Write one `Server` header | Three headers; two of them unknown to the project |
| T13 | Raise a 401 | Two error shapes, split by *where* the refusal happens |
| T14 | Serialise seven fields | Nulls are omitted globally by one setting — resolving an "UNVERIFIED" entry that was waiting for a whole harness |
| T16 | Check in three response bodies | One of the three declared content types serialises differently. The spec, an acceptance criterion and a *passing test* all said otherwise — the test compared Atrium against itself |
| T17 | Assert the routes are registered | Four routing differences, including one the documentation had described as done since T13: an unmatched path was answering `{"detail": "Not Found"}` |
| T18 | Add a CI workflow | Two of the four checks it was to run could not run in CI at all, and the suite's "no network" was a claim with nothing enforcing it |
| T19 | Serialise names differently | Writing one constructor the obvious way — `*args, **kwargs` — silently broke OpenAPI generation, because the framework *inspects that signature* |
| 002 T1 | Answer two open questions | A **fifth** authentication mechanism nothing had listed, and a disabled account refused with `403` where the spec argued for `401` on purpose |
| 002 T7 | Parse a header leniently | Three of the plan's four claims about the grammar were wrong, including the one leniency both documents named |
| 002 T11 | Serve a login screen | `/Users/Public` sends every user's full policy and configuration to a caller with no token — the opposite of the acceptance criterion |
| 002 T14 | Assert no password is logged | The password never leaked; a library logged the password **hash** and another logged the token, both at `INFO`, from one `basicConfig` call |
| 003 tasks | Review a nineteen-item list | Two of the findings were items **missing** from it: no task measured the two questions the spec names probes for, and no task extended the acceptance map — which a test would have failed the day 003 was marked `Implemented` |
| 003 T18 | Store a signal and skip unchanged files | Skipping the read was the easy half. An unexamined music file resolves from its *path*, which hangs it under an album named after its directory — so the second scan of every music library would have silently doubled its albums |
| 003 T19 | Write one test | The claim it exists to prove — "the reference derives ids from the absolute path" — was asserted in two documents and cited in neither. Measured at last: 448 of 448 live ids reproduce from the path alone, **containers included** |
| 003 T20 | Report two things with their reasons | They cannot be one list. One file produced no item and the other produced one. And plan §7 named a failure that does not happen: a `chmod 000` file stats fine, so nothing in 003 ever notices it |
| 003 T21 | Write the acceptance map | A specification row nobody had implemented and no criterion covered — "directory emptied → remove the container item" — which had been there since the spec was written |
| 004–005 gate | Accept two specs, write two plans | The **accepted** 005 spec's error path for enum values does not exist — an unrecognised token is ignored, not `400` — and the reference's own artist-sort paging drops and duplicates rows, which turned "ordering is total" from assumed parity into a documented divergence |
| 004 T5 | Parse a sidecar | Plan §6.2 said the reference does **not** split a genre on ` / ` and cited the parser that does. Not splitting would have given Atrium a genre no reference server has — on a file both of them read, which is the exact disagreement the sentence was written to prevent |
| 004 T10 | Wire the pieces together | The scan and the refresh were **fighting over one column**: every rescan re-derived a name from the filename, every refresh restored the sidecar's, for ever, with every item reported as updated. And the path-derived name turned out to be merged **last**, not third — without which AC-1 is unreachable |
| 004 T15 | Generate a culture table | Plan §6.9's source was wrong three ways. The registry it named has 508 rows to the reference's 192, lists 24 languages' codes in the opposite order, and **cannot produce eight rows the reference has at all** |
| 005 T1 | Copy a field table into a registry | **There is no single item representation.** A bare `/Items/{itemId}` carries up to 39 properties a bare list row does not, `/UserViews` is a third width, and `ChannelId` is an explicit `null` on every item — 208 of 208 — against the reference's own null-suppression setting |
| 005 T12 | Order seasons, specials last | The measurement **reversed the acceptance criterion**: season 0 arrives first, plain index order. "Every client expects it last" was an expectation about clients presented as a fact about the wire — and the fix deleted code, because 003's sort names already produce the measured order |
| 005 T15 | Emit `MatchedTerm`, match the sort name | Neither exists on the wire. Seventeen measured hints never carried `MatchedTerm`, and the discriminating search — a padded sort form no folded name contains — found nothing, settling a spec-versus-plan disagreement the tasks gate had flagged |
| 006 T1 | Add two cells to a probe | A third battery nobody asked for, from subtracting two numbers the probe had been printing side by side since the spec review: `maxWidth=-100` answers `200` at the source's size and **three times its bytes**. A forgiven parameter is not a dropped one — and a bare `quality` does not transform at all, where the plan had made it a reason to re-encode every poster |
| 006 T3 | Implement a measured error shape | The task's own verification cited [behaviours §4.4](docs/compatibility/behaviours.md), an exception **withdrawn three features earlier** by 005 T4 and never marked. Writing the test it asked for would have asserted a raw `ñ` against a response class that escapes it |
| 006 T5 | Assert a containment check | The hostile-path test **passed with the check deleted**: `../../../../etc/passwd` from a `tmp_path` root reaches nothing, so it refused for the wrong reason. Every case now points at a file that exists |
| 006 T6 | Write a resize matrix | **"Never upscale" is not a property of the server.** `maxWidth` and the fill pair cap at the source; `width`/`height` are honoured past it — `width=4000` of a 2000×3000 source is 4000×6000. Implemented literally, Atrium would have sent a *smaller* image than a client asked for by name |
| 006 T8 | Wire four modules together | AC-8 **failed**: deciding the transform from the file's dimensions rather than the row's makes the cache key move whenever the file does, turning every hit into a silent miss |
| 006 T9 | Serve two routes | [Plan §6.6](specs/006-images/plan.md) asks for two things that cannot both hold — a `304` carrying the `200`'s `Content-Type` cannot also be decided before the payload is known. The reference resolves it and drops the body; measured, including `image/webp` on a negotiated `304` |
| 006 T12 | Assert three cache criteria | **The image tag could never change.** `Field.IMAGES` merged under "keep what the item has unless the mode is `Replace`", and v1 has no refresh route to ask for `Replace` — so a replaced poster changed no tag at any scan depth, and client-side cache invalidation was unreachable |
| 006 plan gate | Flip a status line | `fill` never crops — AC-6 reversed on a non-square source, after a square-source probe had measured "exactly the box" — and a resized response negotiates `Accept: image/webp`, the branch the plan's own §10 had just rejected as a delta. Plus a fourth error shape, on the one route that splits its two lookups across two `404` bodies |
| 007 tasks | Review a thirteen-item list | The fixture world has **one runtime**, so the branch a probe had measured had nowhere to be proven; `last_playback_check_in` has no writer at all; OQ-7 belongs to this list rather than to 010; and AC-16's test was written by 003 |
| 007 T2 | Implement a measured rule | **Row 4's second clause decides nothing.** "Within one second of the end" implies "past 90%" for anything longer than ten seconds, and anything shorter is completed by the runtime floor — the spec's paragraph explaining why the clause was *not* redundant had the arithmetic backwards |
| 007 T8 | Wire three routes to a proven core | **The first typed request body answered `{"item_id": …}`** — snake_case on the wire, because the framework keys validation errors on the model's Python field. Nothing had bound a body before, so behaviours §1.1's exact failure was one route away |
| 007 T9 | Serialise a measured item shape | The plan asked for "a field selection derived from the measured width". Reading the property *list* showed the shape is a **subtraction** — a full item body minus a named fifteen — so the existing `omit` mechanism expresses it and `MediaSources` is excluded before 008 exists to emit it |
| 007 T11 | Assert an aggregate nothing was expected to change | **The container `PlayedPercentage` had never been implemented.** AC-20's first half passed because there was no percentage to gate, and its second half was unreachable |
| 008 gate | Answer twelve open questions, write a plan | **Five spec claims did not survive their own probes.** No playback route consults `EnableMediaPlayback` — the error table's `403` was fiction; the body's `EnableTranscoding: false` is ignored; `static=true` on a wrong container is the original bytes behind a lying label, not an error; `enableRedirection` never redirects a local file; and the reference's HLS segments already carry `Content-Length` — half of the project's flagship divergence measured as parity. Plus a defect nobody asked about: a 22 050 Hz sample-rate ceiling is answered at 24 000 — the Opus ladder applied to every codec |
| 008 T7 | Stream a remux and a re-encode | **The test client cannot hang up.** httpx's ASGI transport drives the app to completion and buffers the body, so every "streaming" test here is a buffered one and AC-26's disconnect had to be written at the ASGI boundary. Plus the rule the fixtures found: a stream plan states *every* ceiling, so passing them all asks `libmp3lame` for 96 kHz — a ceiling equal to the source is not an instruction |
| 008 T8 | Synthesise a profile the reference's own way | **Its own way honours no ceiling.** The controller scopes its codec profile to the *direct-play* containers, which are the ones it will never transcode into — the ceiling reaches the encoder only through a second path outside the profile — so a faithful transcription would have answered a 22 050 Hz request at the source's 96 kHz. And the empty `200` beside it is not a codec-less profile: that profile defaults to mp3 and negotiates fine, while the request behind it infers a codec from a URL with no extension |
| 008 T6 | Serve the original bytes, refusing without a token | **The four `stream` routes require none** — no token, an unknown token and `?api_key=` are one `200`, where `/universal` alone answers `401`. 002's accepted spec had said so three days earlier and the task list still said the opposite; implemented as written, every bare URL handed to an external player would have broken. Plus a `404` in the *third* error shape, where the same identifier is problem details one route away |
| 008 T14 | Write the acceptance map and flip three status lines | **Two criteria said something their own tests contradict, and two more were mapped to tests that proved less than their names.** `SupportsTranscoding` follows the *profile*, not the answer; *"every delivery route whose body has a known size answers `Accept-Ranges: bytes`"* is false of the two playlists, measured on both servers. Nothing had ever compared the `Size` a negotiation advertises with the bytes the route serves, and `audioStreamIndex` was asserted as a string in a URL and never as a property of the audio that came back. And the definition of done's *"no other response differs observably"* was false: a progressive re-encode produced to a **pipe** carries no MP3 header frame and no completed FLAC `STREAMINFO` — a fourth divergence, and the only one pointing away from the reference |
| 011 gate | Answer twelve open questions and accept a spec | **Four died, and the sharpest inverts the feature.** The master playlist does not accept the manifest flag at all — the reference's own negotiation writes it into the address and the route it addresses cannot read it — so the *only* lever is the delivery address naming the manifest method, which is the client-side override the trace had sized as a line inside the real work. Burn-in is not a branch the reference avoids but the answer it gives on every track no profile fits; the default subtitle track is **never** the highest-scoring stream, because the score is only ever read to detect a tie and the profile then decides outright; a posted subtitle index is dropped in silence unless the request also names the media source. Plus a defect nobody asked about: a subtitle playlist's window durations are formatted in the **server's locale**, so a Spanish host writes `#EXTINF:7,851,` — and `playSessionId`, recorded as an improvement to argue for, turned out to be something the reference already does on three routes of four |
| 012 gate | Answer nine open questions and accept a spec | **The feature turned out to be half the size it looked, and the half that went was one already reported to the user.** A listing on a stock reference answers a never-opened source exactly the way Atrium does — empty streams, no runtime, three flags `true`, no address — so the music client's four losses are **parity**, not a gap. What is not parity is the negotiation: it **opens the file inside the request**, comes back fully annotated in 0.20 s, and **keeps** what it learns, so the next listing carries it. *"One root cause, two clients"* survives, through the write rather than the read. Plus an answer nobody predicted: an **audio** item with no audio stream refuses the whole body with `400` where a video item answers `200`, and the address that `200` hands over resolves to a live playlist answering `500`. The protocol question needed four classes where the draft had two — altered cases bind, ordinals bind (`2` comes back as the number `2`), an empty string takes the default, and only an unbindable word refuses. And the initialisation-segment restart the client contract sized as a defect is guarded by a file check every producing session has already satisfied: 0.03 s against 0.69 s, nothing discarded |
| 009 gate | Answer six open questions and accept a spec | **Thirteen claims died, and the first one takes the feature's central idea with it.** `PlaylistItemId` **is** the item's `Id` — the field is a cache of the resolved item, so the entry identity §3.1 was built around, warned client authors about and asserted in an acceptance criterion is a distinction the wire does not make; it is also *why* the reference de-duplicates, which a probe had measured four days earlier without anyone connecting the two. The read route takes the identity it checks permissions against from a query parameter and never asks whether the caller may name it, so a restricted user reads any private playlist by naming its owner — where the same parameter on the same controller's write route answers `403`. A playlist shows entries from libraries the reader cannot open at all, because the filter in front of them is a parental-rating check: the omission the spec described as the reference's behaviour was never anyone's. Every row of the `Move` boundary table was wrong — a clamp exactly one position wide and a `500` past it, a negative index that moves the entry instead of refusing it, an absent entry that is a silent success. An empty `Name` creates a playlist where the spec promised `400`, an unknown id is fatal to creation under one condition and skipped under another, and refusing a deletion is `401` and not `403`. Plus the scope finding: the rename the music client calls is administrator-only, so the operation brought into the surface for that client refuses that client's own users |
| 008 T9 | Answer two broken WAV routes and pay a prior-probe debt | **Both prior-probe claims moved when the probe was finally written.** The `500` has two causes, not one — a `wav` extension inferred as a *codec* never reaches the PCM bug at all — and the headerless body comes from the **transcoding** container, so the acceptance criterion's `Container=wav` named a request that answers mp3 on both servers. And the divergence has no chunked form: a WAV states its length inside the body, so a piped one says `ffffffff` |
| 011 tasks | Review a twelve-item list against an accepted plan | **The plan's manifest section had been true when it was written, and stopped being true the same day.** 008 was amended hours earlier to offer an HDR stream copy a standard-range entrance, so "the variant line gains the subtitle group" would have shipped an entrance with no subtitles to exactly the client the entrance exists for — the reference gives the group to every variant it writes. Three more: the text/image split reads a codec spelling **the file does not report**, because four subtitle codecs are renamed at inspection, and against the unrenamed names the rule inverts on every DVD and broadcast track there is — a property 008 already emits, invisible because no fixture had a subtitle stream; the embedded **image** subtitle track the fixture needs cannot be encoded by ffmpeg at all, so it is a bitstream written by hand; and a sidecar's language rule names "the eight regional rows" of a table that has nine, two of them not regional |
| 009 T14 | Write the acceptance map and flip three status lines | **A criterion with no test at all, two that proved less than their names, and one that says what its own tests contradict.** AC-20 — *"playlist state survives a full library rescan"* — had never been asserted, on the one item in the store a rescan cannot rebuild: **two** independent clauses keep a playlist out of the scan's removal pass — it has no library, and it is not file-backed — and neither was written down as load-bearing; remove both and the operator's purge deletes the playlist row outright. AC-5's *"on both the creation and the addition paths"* had only ever asked the addition, where `create` reduces its batch somewhere `append` does not; AC-13's *"the same three routes answer `404`"* had asked one of the three, and the two it skipped include the **move** — the route whose refusals are ordered, so a route reaching its editing test first would have disclosed a private playlist with a `403`. And AC-15 asserted that naming a playlist's owner in `userId` is part of the `404` it describes: it is the 25-byte `403` `effective_user` answers on every route in the project that takes the parameter, which is what AC-16 and AC-19 already said |
| 011 T12 | Write the acceptance map and flip three status lines | **A risk the plan had named fired, and the mitigation it prescribed could not have caught it.** `-map 0:{N}` was handed the **wire** stream index where ffmpeg counts the demuxer's, so every remux, transcode and HLS segment of a film with a subtitle file beside it mapped one stream too far: measured, a remux of the one matrix entry with a sidecar answers `200` carrying **no video stream at all**. Plan §5 states the contract — `media/ffmpeg.py` maps `file_index` — §9 predicted this exact failure, and the test it prescribed asserts a property of `renumber` rather than of anything that reads it; meanwhile T1 had deliberately put the sidecar beside a film 008 asserts nothing about, which left every produced-bytes test in the repository running over a source with no external stream. Four criteria were mapped to tests that proved less than their names: AC-1's *listing row* had only ever been asked as a bare item, AC-11's `HasSubtitles` was asserted on a film carrying an embedded track too, AC-12's *"affects neither the item nor its user data"* had nothing at all, and two rows of the §3.7 table had no test. And the definition of done's two divergences are two: burn-in is a **third** observable difference, and it is an accepted gap rather than a divergence |
| 010 gate | Answer four open questions and accept a spec | **None of the four survived, and the two sharpest findings were not among them.** The remedy OQ-1 proposed is not on the wire: `Path` is absent from **every** default list row — 0 of 1000 — so a run joining on it compares a request no client sends, and asking for it still leaves a virtual season, a remote channel and every by-name row unjoinable, with the paths those rows *do* carry naming the reference installation's own data directory; `(Type, Name)` is 976 distinct of 1000. A recorded session replays faithfully — 16 of 19 reads byte-stable, only the response time and the clock moving — and still cannot be the gate, because a recording answers only the requests it recorded and the defect class L3 exists to find is the field nobody thought to ask for. OQ-4's two non-deterministic endpoints are **three**: `/UserViews` answers a fresh random `ChildCount` between 1 and 9 on every request, on every view, because the reference declines to count a top-level folder and substitutes a number so clients "won't think the folders are empty" — and the field-level allowlist the spec described cannot express any of them, because what needs excusing is a whole array. Plus two differences nobody asked about, both against an **implemented** feature: `/Items/{itemId}/Similar` is not a ranking at all but a random draw over items sharing the seed's genres and tags — four identical requests shared **no** item — and on a **movie** seed `limit=N` answers **N + 4**, exactly, where a series, an album and an artist answer N. And the harness requirement 009 T14 predicted, measured: **12 of 23 reads of the surface answer differently to a restricted non-administrator**, two of them not as refusals but as shorter lists, so every measurement this repository had ever taken was from a seat that could be refused nothing |
| 010 plan | Write a plan for a harness the documents already describe | **Four of the things the documents describe are not there, and one accepted criterion fails the document that ships it.** `tools/differential.py` is a command line [conformance.md](docs/compatibility/conformance.md) publishes — flags, report path and all — for a program nobody has written; the `ATRIUM_JELLYFIN_URL` the same document names as the switch that makes L3 opt-in appears **nowhere** in the repository, so the mechanism is real and the name is a claim about an implementation that does not exist. The prior-measurement register is stale in four rows: its prose says *"six down, nine to go"* where seven of fifteen are struck, and **three of the eight open debts have in fact been paid under another script's name** — the authentication mechanisms by `probe_auth_mechanisms.py`, which is what turned four into five, while `api-surface-v1.md` still cites `prior-probe: 2026-06-13` for four of them. And AC-6 — *"an allowlist entry without a behaviours.md reference fails the run"* — fails the allowlist its own spec ships: three of eight field rows and one of three array rows name a section, and the reference's random `ChildCount` has no entry there at all. Plus the one that decides a mechanism: `ChildCount` is a **computed subtree aggregate in this server**, so the flat field-name allowlist both documents describe would excuse, on every container, the value L2 exists to check |
| 010 T15 | Write the acceptance map and flip three status lines | **The status lines did not flip that day** — they flipped after D-7, on the criterion rather than on the evidence. A criterion with no test at all, a criterion half with no test, and a criterion whose own measurement contradicts it. **AC-11** — *"the default CI job passes with no Jellyfin available and no network access"* — was mapped to *"CI, unchanged"* and asserted **nowhere**, in the one feature whose entire value is a second server and which is therefore the likeliest to grow a test that needs one; the guard is proven by making it fire now, and the `needs_reference` sweep names the only test in the repository allowed to carry it. **AC-7** is two claims joined by *and* and only the exit code was ever asserted: *"prints a citation in the documented form"* had no test on either side of the run, and a citation is what turns a finding into provenance. And **AC-2** — *"both servers, pointed at the same built fixture, produce libraries with the same item count and the same structure"* — is contradicted by the comparison written for it: **forty-seven declared differences**, of which twenty-five are one file named two ways and twenty-one are container rows, every one belonging to 003 or 004, which the feature's own §2 puts outside it. It is the only one of the eighteen that asserts a property of *Atrium* rather than of the harness. Plus the levels finding: the report's coverage table said `Compared: yes` from a **flat set**, so a row reached by the administrator alone read like one both seats reached — on a surface where 12 of 23 reads answer differently to a restricted non-administrator, which is this feature's own characteristic failure arriving inside its own report. **D-7 was taken on 2026-09-02 and AC-2 now states the recorded comparison**, so the six documents moved together in that commit — the flip followed the decision rather than the other way round |
| 008 fix | Apply the all-three playback gate the negotiation was missing | **The gate that was missing was not the all-three gate, and implementing it would have shipped a second wrong answer.** The harness row negotiates with an **empty body**, and against no profile the reference reaches no stream builder for that gate to apply to: it reads **one** permission per media kind off the source, so a video item's `SupportsTranscoding` is `EnableVideoPlaybackTranscoding` and its `SupportsDirectStream` is `EnablePlaybackRemuxing`. A single denial is therefore observable on `GET /PlaybackInfo` and invisible one branch away — and the all-three gate on the profile-less branch would have answered `true` for a seat denied video transcoding alone, where the reference answers `false`. Two more beside it: the named comparison's own prediction of *two different delivery statuses* was unreachable, because it asks one of the four `stream` routes and those take **no user** here at all; and the probe's picker took the library's first film, which in the fixture tree is dummy bytes and then a film with two subtitle tracks — so it measured 011's subtitle rule and reported it as a ladder finding |
| 005 fix | Copy the per-media-kind rule 008 had just written onto the listing | **The rule was right, its scope was not, and the fix is a field with no default.** 008's own entry asserted in prose that a listing carries the same flags *"measured on the same run"*; nothing in this repository measured it, and a listing battery run against the single-use reference instance found three things that run could not have said. A source **nothing has ever inspected** is not exempt — which matters because behaviours §2.23 describes that shape as *"the three capability flags all `true`"*, and three flags `true` is the **permitted account's** answer rather than the shape's. The policy is the **effective** user's and not the caller's, so an administrator naming a denied account in `userId` is answered that account's flags. And a request naming **no** user is the token holder's policy rather than none — the one reading that would have made an administrator's own answer wrong. The gap's own row had named the trap and the fix took it seriously: `BuildContext` is built in **fifteen** places in `api/`, so `policy` is a **required** field — a route that emits an item cannot be written without deciding whose permissions it emits under, where a permitted default is exactly what a forgotten route would ship in silence. `/Sessions` had also been sharing one context across playing users, which was invisible while nothing in it read the account |
| 002 fix | Withdraw one `403` a probe had already contradicted | **The cell that was measured was not the route.** 009 T2 had measured a *restricted* non-administrator naming an *administrator*; the whole matrix says the reference refuses **nobody** — an ordinary non-administrator reads another whole, and the administrator's object read by a stranger is byte-identical to the administrator's own reading, so there is no per-caller representation to build. And the refusal that was withdrawn was hiding two more: an identifier no account has is `404` with the **fourth** error shape, `"User not found"`, the same body to an administrator and to a non-administrator, and a malformed one is the validation `400`. Atrium had answered both with the same `403` so that a caller who may not look could not tell them apart — and there is nobody who may not look |
| 004 fix | Give a two-disc album the directory its discs sit in | **The proposed rule was worse than the defect, and the defect was two containers wider than reported.** The common ancestor of a container's files answers the two-disc album and scores **12 of 17** over the fixture tree against the standing rule's 15: a series with one season borrows that season's directory, an artist with one album borrows that album's. The reference's own answer was already in this repository, unread — of the 26 container rows its recorded reading makes of the fixture, the 18 carrying a directory and a kind Atrium's tree has sit at exactly that kind's depth below the library root, disc directories included — so the rule is counted **down from the root**, and scores 17 of 17. Beside the album, the **artist** above it was borrowing the album's own directory, so no artist with a disc-split album anywhere beneath them could reach an `artist.nfo`; and a track sitting directly in an artist's directory gave that artist the **parent of the library root**, where a refresh read a sidecar outside the library it was scanning — `artwork.associate` refuses a file outside the root and warns, and `find_sidecar` never had that guard |

The tools for it are in [`tools/`](tools/): `.env` carries the credentials, the probes answer one
question each, and a plain `urllib` request answers the rest.

**Licence: GPL-3.0-or-later** ([ADR-0005](docs/decisions/0005-licence.md)). Every source file
carries `# SPDX-License-Identifier: GPL-3.0-or-later` from its first commit. The licence is a
backstop for an honest mistake, not permission to translate Jellyfin's code — Principle IV still
binds.

## Rules that bite immediately

**English, everywhere.** Code, comments, identifiers, commit messages, branch names, docs. No
exceptions (Principle IX).

**Documentation moves with the code, in the same commit.** A behaviour change whose spec is updated
"in a follow-up" is an incomplete change, not a fast one (Principle III).

**No technology names in `spec.md`.** No Python, no library, no table, no module, no function. Those
belong in `plan.md`. This is the rule most often broken and the one whose breach destroys the
method.

**Every claim about Jellyfin carries provenance**, inline, in one of three forms (Principle II):

| Form | Use it for |
|---|---|
| `[probe: tools/probe_x.py, Jellyfin 10.11.11, 2026-08-26]` | Measured by a script in this repository |
| `[prior-probe: Jellyfin 10.11.11, 2026-06-13]` | Measured against a real server before this repository existed. Real, not reproducible from here — a debt, not a licence to skip writing the probe |
| `[source: path/File.cs:123 @ v10.11.11]` | Anything read from Jellyfin's code |
| `[spec: OperationId]` | Anything taken from the pinned OpenAPI document |

**Never cite a path outside this repository.** Provenance names a *version and a date*, or a file
inside Jellyfin's own tree. Private repositories, internal documents and local paths do not appear
in citations — they are neither verifiable by a reader nor ours to publish.

A claim with no provenance is marked `⚠️ UNVERIFIED` and keeps its spec in draft.

**Never copy Jellyfin's code** (Principle IV). Read it to learn *what it does*; write your own
implementation. Transliterating a C# method into Python is a licence problem and a design problem
at once.

**Zero delta** (Principle I). No endpoint, field, casing or unit that Jellyfin does not have. A good
idea that creates a delta goes in
[behaviours.md §6](docs/compatibility/behaviours.md#6-non-improvements) and is then not done.

**Dates are absolute.** `2026-08-26`, never "recently".

**Verify that an edit landed.** A `pyproject.toml` change once matched nothing and reported success
because another tool had rewritten the block underneath it. A scripted edit that cannot fail is a
scripted edit that will silently not happen.

## Where things live

| You want to… | Go to |
|---|---|
| Understand a decision | [docs/decisions/](docs/decisions/) |
| Know if an endpoint is in scope | [docs/compatibility/surface.yaml](docs/compatibility/surface.yaml) |
| Know what a real client actually needs | [client-atrium-tvos.md](docs/compatibility/client-atrium-tvos.md) (video) and [client-embeat-mobile.md](docs/compatibility/client-embeat-mobile.md) (music) — the two `consumers:` tags, traced back to their authors' own contracts, plus — for the video client — the intent behind its on-device path, which no contract states |
| Know what a Jellyfin term means | [docs/glossary.md](docs/glossary.md) |
| Know how a behaviour gets proven | [docs/compatibility/conformance.md](docs/compatibility/conformance.md) |
| Know what comes next | [docs/roadmap.md](docs/roadmap.md) |
| Know what the last audit found, and what is still open | [docs/audits/](docs/audits/) |

## Contributing a fix upstream

Sometimes the right response to a reference defect is to fix it in the reference. Two things make
that harder than it looks, and both are worth knowing before starting:

- **Jellyfin does not accept contributions authored with AI assistance**, and every commit in this
  repository carries a `Co-Authored-By` trailer. An upstream patch has to be a separate,
  hand-authored artefact — not a cherry-pick from here.
- **An issue is often the better artefact anyway.** A hand-written issue describing the behaviour,
  proposing no code, gets the defect judged on its merits. That judgement is what
  [behaviours §3.0.1](docs/compatibility/behaviours.md#301-the-tie-breaks) tie-break 2 needs, and a
  closed pull request does not supply it.

Either way, **upstream is not a dependency**. A defect is decided here, on the evidence available
here, using the procedure in
[behaviours §3.0](docs/compatibility/behaviours.md#30-how-the-decision-is-made). Waiting for
upstream is not a plan.

## Reference material

Not vendored — fetched into a git-ignored `reference/` directory:

```bash
python3 tools/fetch_reference_spec.py http://your-jellyfin:8096
python3 tools/extract_v1_surface.py --spec reference/openapi.json --print-summary
```

A local checkout of Jellyfin's source at `v10.11.11` is the second reference input. Neither is
required to work on documentation, and neither may be copied into this repository.

## Adding an endpoint

1. It has a named consumer, or a written reason under Principle VI.
2. It is in `docs/compatibility/surface.yaml`, with its consumers, feature and conformance level.
3. `tools/extract_v1_surface.py` passes.
4. It is specified in the owning feature's `spec.md`, with request, response, error paths and
   provenance.
5. Only then, code.

## Adding a compatibility claim

1. Measure it — probe script, or a cited source line with a version tag.
2. Record it in `docs/compatibility/behaviours.md` with the three required fields: what Jellyfin
   does, whether a client depends on it, what Atrium does.
3. If Atrium diverges, the entry carries the argument for why no client can observe the difference.
