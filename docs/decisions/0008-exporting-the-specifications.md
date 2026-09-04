# ADR-0008 — Exporting the specifications, and what a second implementation may inherit

**Status:** Accepted · **Date:** 2026-09-04

## Context

[specs/README.md](../../specs/README.md) states the test this project applies to its own
specifications: *"two competent engineers could implement it in two different languages and their
servers would be indistinguishable to a client"*. Nothing has ever applied it. Every claim this
repository makes about the quality of its `spec.md` files is a claim about a document that has been
read by one implementation, in one language, by the people who wrote it.

The test is runnable. Copy out the language-neutral half, hand it to a second implementation in
another language, and judge both against the same reference with the same harness — which
[010](../../specs/010-conformance-harness/spec.md) built and which already takes a base URL rather
than a process. What stops it is not the harness: it is that **nobody has said which documents a
second implementation is entitled to inherit**, and a copy that includes the wrong half proves
nothing.

That is the decision this record takes. It is not "should there be a second implementation" — that
is somebody else's project to start. It is: *if one is started, what does it get, what does it have
to earn, and how does either side know which snapshot it agreed on.*

## Decision

**A command — `tools/export_specifications.py` — that copies the language-neutral half of this
repository into an empty directory, refuses to copy the rest, and writes down which is which.**

**`spec.md` travels; `plan.md` and `tasks.md` do not.** The three artefacts are WHAT/WHY, HOW and
STEPS ([specs/README.md](../../specs/README.md)), and a second implementation that starts from the
first one's plan is a transliteration. It would measure the plan, not the specification — and the
specification is what is on trial.

**The compatibility documents travel whole.** `behaviours.md`, the two client contracts, the
surface, the conformance levels and the recorded readings are measurements of **Jellyfin**, not
decisions of this implementation. Re-deriving them would be paying twice for the same reading, and
paying the second time against a reference that has moved.

**Four of the eight architecture decisions travel** — 0001 (implement the Jellyfin API), 0004 (the
pinned version), 0005 (the licence) and 0007 (the single-use reference instance, which is a method
rather than a runtime). The stack, the store, the password hashing and *this record* are decisions
the receiving project takes for itself.

**Nothing under `tools/` travels, and that is reuse rather than refusal.** Every probe takes a
server address and `differential.py` takes `--atrium <base URL>`, so the harness is **pointed at**
the second implementation over HTTP instead of being written twice. It follows that naming a
`tools/` script inside an exported document is not a leak, in a citation or bare; naming anything
under `src/` or `tests/` is.

**Every tracked path is classified or the export fails.** A path that is neither exported nor
withheld exits non-zero and names itself. This is the allowlist discipline of
[conformance.md](../compatibility/conformance.md) applied to a second question: an undeclared thing
is a failure, never a default, so a document added next month cannot be quietly left behind or
quietly shipped.

**It reports; it never edits.** The exported bytes are the bytes at the ref. Three things that are
true here and wrong in the new home are written into the destination's `PROVENANCE.md` rather than
fixed: prose that names a technology or points into `src/`, a `status:` that is a statement about
*this* project, and links whose target was withheld. Retargeting a link or resetting a status is an
edit to a specification, and that belongs to whoever receives it.

**The ref is the experiment.** `--from HEAD` exports the specifications as amended and asks whether
a mature specification is complete enough for another language to arrive at the same place.
`--from <the commit that accepted them>` exports them as written before any code existed and asks
the harder question — whether the loop finds the same things again, with this repository's
`amended:` frontmatter as the answer sheet. They are different experiments and they do not share a
destination.

## Consequences

**The leak census is the honest part, and the first run does not survive it.** Measured at
`681b083` on 2026-09-03: **157 lines**, and where they are is the finding. Three lines across the
twelve `spec.md` files — so the rule *no technology in a spec* holds almost exactly — against
**108** in `behaviours.md` and the two client contracts, which cite this implementation's own
modules as the evidence that a client requirement is bound. Those documents were never written to
be portable, and this is the first thing that has ever asked them to be. `--strict` turns the
census into a failure for whoever wants that gate; the default reports it.

**A snapshot is nameable.** `PROVENANCE.md` carries the resolved commit and a digest over the
exported bytes, so a later claim that two implementations agree names the specifications they agree
*on*. Without it, "we both implemented the spec" is a sentence about a moving target.

**The command is a check on this repository whether or not anybody exports.** It fails on a tracked
path nobody has classified, so it is a standing question — *is this document a specification or an
implementation detail?* — asked of every file added from now on.

**It is not in CI.** Nothing here gates a change: the export is an experiment somebody runs, and
the leak census is a reading rather than a rule. Wiring `--strict` into a job would make 157 lines
of compatibility prose a blocker for work that has nothing to do with them.

## Alternatives rejected

**Export everything and let the receiving project delete what it does not want.** The refusal *is*
the decision. A second implementation that has the plan will read the plan — not out of weakness,
but because it is there and it answers the question in front of them — and the experiment is over
before it starts.

**Export nothing, and let a second implementation read this repository on GitHub.** The same
failure with an extra step, and no snapshot: whatever it read, it read at whatever moment it
looked, and no later comparison can say which documents were on trial.

**Hand-maintain a list of exportable files.** That is what the manifest is, with one difference
that decides it: an unclassified path is a **failure** rather than an omission. A hand-maintained
list silently stops being complete the first week nobody remembers it.

**Rewrite the leaks on the way out — strip technology names, retarget links, reset statuses.** It
would make a cleaner export and a dishonest one. A specification that needs 157 edits to be
portable is a specification with 157 things to say about it, and hiding them in a transformation
means the second implementation never learns what it was handed.

**Fork the repository and delete the implementation.** It carries the git history, which carries
the plans, the tasks and the code. The point is a virgin project.
