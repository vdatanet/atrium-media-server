# ADR-0009 — A document that contracts is not a surface that shrank

**Status:** Proposed · **Date:** 2026-09-12

## Context

[reference-target §1](../compatibility/reference-target.md#1-the-pinned-version) pins **two** rows,
not one: an **API contract** — a named OpenAPI document — and a **behavioural reference** — a named
source tag and a running instance. [conformance.md](../compatibility/conformance.md#the-two-rows-move-separately)
already knows they can move apart, and spells out one of the two ways:

> **When only the contract row moves — same server, a different document of it — step 2 has no
> input.** Nothing behavioural changed, so there is no new difference for a differential harness to
> triage.

That paragraph was written for the move actually made on 2026-09-01, `10.11.10` → `10.11.11`, where
the document moved to catch up with a server that had been `10.11.11` all along. **The other way
round was never considered**, and Jellyfin `12.0.0` produced it.

### What the 12.0.0 document does

The operator's reference server was upgraded from `10.11.11` to `12.0.0` between 2026-09-10 and
2026-09-12. Fetching its document and running the surface validator reports **five of the fifty-nine
endpoints in [surface.yaml](../compatibility/surface.yaml) as gone**
`[probe: tools/fetch_reference_spec.py + tools/extract_v1_surface.py, Jellyfin 12.0.0, 2026-09-12]`:

```
error: GET /MusicGenres: path not present in the pinned document
error: GET /Videos/{itemId}/master.m3u8: path not present in the pinned document
error: GET /Videos/{itemId}/main.m3u8: path not present in the pinned document
error: GET /Videos/{itemId}/hls1/{playlistId}/{segmentId}.{container}: path not present…
error: DELETE /Videos/ActiveEncodings: path not present in the pinned document
```

All five are declared by the `10.11.11` document and absent from the `12.0.0` one — 316 paths
against 295 — and four of the five are one subsystem: the whole **video HLS delivery path**, which
is 008's remux and transcode answer and therefore the delivery half of a v1 promise.

Read as step 1 instructs, that is five breaking changes, one of them catastrophic.

### What the 12.0.0 server does

**All five are still served.** Asked of the running reference the same day
`[probe: manual requests via tools/_probe.py, Jellyfin 12.0.0, 2026-09-12]`:

| request | answer |
|---|---|
| a path the server genuinely does not have | `404` |
| `GET /Videos/{bogus-id}/master.m3u8` | `400` |
| `GET /Videos/{real-id}/master.m3u8?videoCodec=h264&audioCodec=aac` | **`200`**, a playlist |
| `GET /MusicGenres` | **`200`** |
| `DELETE /Videos/ActiveEncodings` | `400` |

`404` is what this server answers for a route it does not have, so `400` and `200` are routes that
exist. The same five are absent from the `--raw` document too, so this is not
`fetch_reference_spec.py`'s sanitising passes removing them.

**The document contracted. The surface did not.**

### Why this is a defect in the procedure and not a surprise about Jellyfin

The repository already ranks these sources against each other, and the order is not the one step 1
uses. [reference-target §2](../compatibility/reference-target.md#2-sources-of-truth-in-precedence-order),
*"when two sources disagree, the higher one wins"*:

1. a running Jellyfin — *"the only source that reflects what clients actually receive"*;
2. the Jellyfin source at its tag;
3. **the OpenAPI document** — last, and the section gives three worked examples of it being
   *"demonstrably not a complete description of behaviour"*.

Step 1 of the bump procedure consults **only** source 3, and
[`tools/bump_reference_version.py`](../../tools/bump_reference_version.py) turns its output straight
into a verdict: *"A path or method that disappeared is a breaking change to record before the pin
moves, not an error to work around."* On this bump that verdict is false five times out of five,
and it is false in the direction that costs most — it would have reported that Jellyfin dropped
HLS video delivery, which no measurement supports and which would have dominated every argument
about the move.

Nothing in the procedure is wrong about *documents*. What is wrong is that a step reading the
lowest-ranked source is allowed to **conclude** on its own, in a repository whose whole method is
that a claim is worth what its measurement is worth.

## Decision

**A path the new document does not declare is a question for the running reference, not a finding.**
Step 1 may raise it; only the server may answer it.

Every endpoint the new document lacks is resolved into exactly one of three outcomes, and each is
recorded by name:

| Outcome | Test | What it means |
|---|---|---|
| **withdrawn** | the running reference answers `404` | A real breaking change. The row is recorded against the move, and this is the case step 1 was written for |
| **undocumented** | the running reference serves it | The document contracted and the surface did not. Not a breaking change, and not a reason to remove the row from `surface.yaml` |
| **unasked** | it could not be asked | Neither of the above may be assumed. The bump stops here, the way it already stops when it cannot read the reference's version at all |

**Step 1 no longer returns a verdict on its own.** It returns the questions; the resolution is part
of the same step and needs the running reference, which the bump program **already holds** — it asks
that server its version before step 1 runs, in order to classify the move. No new input, no new
credential, and no new mechanism: this is the existing precedence order applied to a step that was
skipping it.

**This record decides nothing about moving to 12.** It does not move a pin, does not accept or
refuse the bump, and does not settle what an `undocumented` row costs a feature. Step 2 — the
differential — is mandatory for this move by the program's own measurement and has not run; it is
blocked on an unrelated recorded condition, that
[a running Atrium cannot be given a library](../../specs/010-conformance-harness/tasks.md). What is
decided here is only what step 1 is allowed to say, and it is decided now because it is independent
of the answer: the procedure would have mis-stated this bump whichever way the bump goes.

## Consequences

- **Step 1 gains a measurement and loses an inference.** `tools/extract_v1_surface.py` keeps its
  job — it reads a document and says what the surface claims that the document does not — and the
  sentence turning that into *"a breaking change"* moves out of it and into a step that can ask a
  server. The regex the bump program matches on (`DISAPPEARED`) becomes the input to a question
  rather than the evidence for a conclusion.
- **A run with no reachable reference of the new version cannot complete step 1.** Today it can:
  the document is a file and the check is offline. This is a real narrowing, and it is the same
  narrowing step 2 already imposes — *"a bump that skips step 2 has not been done; it has been
  declared"* — for the same reason.
- **`surface.yaml` needs somewhere to record `undocumented`.** Five rows would otherwise fail the
  validator on every run after the pin moved, and the honest fix is not to delete them — they are
  served, and Atrium serves them — but to record that their provenance is the running server and
  the source rather than the document. Which spelling that takes is left to the task that does it;
  what this record fixes is that deleting the row and recording a breaking change are both wrong.
- **Provenance survives.** *"An endpoint enters the table with its provenance, or it does not
  enter"* is unchanged, because §2 already admits three sources and the document is the weakest of
  them. An `undocumented` row is not a row without provenance; it is a row whose provenance is the
  two stronger sources.
- **It costs Principle I nothing.** Nothing here adds an endpoint, changes one, or invents a
  dialect. Atrium serves exactly what it served before this record.
- **The asymmetry is now covered in both directions**, which is the smaller reason to write it
  down: conformance.md handles a contract row moving alone, and this handles a contract row moving
  *backwards* while the behavioural row moves forwards.

## Alternatives rejected

**Take the document as authoritative and record the five as breaking changes.** This is the current
procedure, and it is refused because it is measurably false: the routes answer `200`. It also
contradicts §2's stated precedence in the one situation that precedence exists for — two sources
disagreeing. Adopting it would put *"Jellyfin 12 removed HLS video delivery"* into this
repository's documents, where it would be cited by the next reader and be wrong.

**Take the server as authoritative and drop the document check.** Refused: the document is the only
source that catches what a path-level probe cannot see — a parameter renamed, an enum member added,
a schema field's type changed. §2 keeps it for exactly that, *"the shape of requests and responses,
parameter names and enum vocabularies"*. Losing it to fix an over-reach would trade five false
findings for an unknown number of missed ones.

**Say nothing, and let whoever runs the bump notice.** Refused on the evidence of this run: the
validator's output reads as five flat assertions of fact, and the only reason they were not
believed here is that somebody asked the server a question the procedure does not ask. That is the
definition of a check this repository would not accept anywhere else — *"a status line that
overstates the work is the one thing 010 exists to prevent in others"*.

**Wait for step 2 and decide it all at once.** Refused because the two are independent. Step 2 is
blocked on a condition that has nothing to do with documents, and its outcome cannot change what
step 1 should have said about a route that serves. Bundling them would delay a correction to the
procedure behind a measurement that needs an operator's hand.
