# AGENTS.md

Guidance for anyone — human or agent — making changes in this repository.

## Read first, in this order

1. **[docs/constitution.md](docs/constitution.md)** — ten principles that override everything else,
   including this file.
2. The **`spec.md`** of the feature you are touching, under [specs/](specs/).
3. **[docs/compatibility/behaviours.md](docs/compatibility/behaviours.md)** — the measured
   behaviours you must reproduce, including the defects we reproduce on purpose.

## Where the project is

**Features 001 through 008 are implemented** — **[008](specs/008-playback-negotiation-and-delivery/)
landed on 2026-08-29 across fourteen tasks**, spec, plan and tasks all accepted the same day and
every one of the fourteen finding something the documents had wrong. Playback is therefore in: the
negotiation, the four `stream` routes, `/universal`, the HLS playlists and segments, and a
supervised encoder per play session. **[011's spec was accepted on 2026-08-29](specs/011-subtitle-delivery/spec.md)** at its own
measurement gate — twelve open questions answered by five new probes, four of them overturned —
and **[its plan was accepted on 2026-08-30](specs/011-subtitle-delivery/plan.md)** — the plan
that found the reference writes the track name itself, so the localised property 008 withholds
is one 011 cannot. **[Its twelve-task list was accepted the same day](specs/011-subtitle-delivery/tasks.md)**,
at a gate whose sharpest finding was a plan sentence that had been true when it was written: the
manifest's subtitle group goes on *"the variant line"*, and 008's own T15 had given an HDR stream
copy a second variant hours earlier — so **011 is ready for code, starting at its T1**.
**[012's spec was accepted on 2026-08-29](specs/012-negotiation-inputs/spec.md)**,
at a gate that answered its nine open questions with two new probes and two extended ones and
withdrew one of the two client findings it was built on. **009 and 010 are specified only, their
specs still drafts**, so 009's spec review is the next gate of the loop. What each implemented feature leaves the ones
after it is written at the end of its own task list rather than here, so it cannot go stale:
[008's](specs/008-playback-negotiation-and-delivery/tasks.md#what-this-feature-owes-the-next-ones)
is the longest, and 010 collects most of it;
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
| 008 T9 | Answer two broken WAV routes and pay a prior-probe debt | **Both prior-probe claims moved when the probe was finally written.** The `500` has two causes, not one — a `wav` extension inferred as a *codec* never reaches the PCM bug at all — and the headerless body comes from the **transcoding** container, so the acceptance criterion's `Container=wav` named a request that answers mp3 on both servers. And the divergence has no chunked form: a WAV states its length inside the body, so a piped one says `ffffffff` |
| 011 tasks | Review a twelve-item list against an accepted plan | **The plan's manifest section had been true when it was written, and stopped being true the same day.** 008 was amended hours earlier to offer an HDR stream copy a standard-range entrance, so "the variant line gains the subtitle group" would have shipped an entrance with no subtitles to exactly the client the entrance exists for — the reference gives the group to every variant it writes. Three more: the text/image split reads a codec spelling **the file does not report**, because four subtitle codecs are renamed at inspection, and against the unrenamed names the rule inverts on every DVD and broadcast track there is — a property 008 already emits, invisible because no fixture had a subtitle stream; the embedded **image** subtitle track the fixture needs cannot be encoded by ffmpeg at all, so it is a bitstream written by hand; and a sidecar's language rule names "the eight regional rows" of a table that has nine, two of them not regional |

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
