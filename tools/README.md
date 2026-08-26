# tools

Scripts that keep the documentation honest. None of them is part of the server.

## Reference material

| Script | Purpose |
|---|---|
| [`fetch_reference_spec.py`](fetch_reference_spec.py) | Fetch and sanitise the Jellyfin OpenAPI document from a running server into the git-ignored `reference/` directory |
| [`extract_v1_surface.py`](extract_v1_surface.py) | Validate `docs/compatibility/surface.yaml` against that document — the automated half of Principle VI |

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
| [`probe_routing.py`](probe_routing.py) | How does the server match a path to a route, and how does it refuse? | 001 §3.6 | no |
| [`probe_query_envelope.py`](probe_query_envelope.py) | What shape does each list endpoint return? | 005 OQ-6 | no |
| [`probe_sort_names.py`](probe_sort_names.py) | How does the server derive `SortName` from `Name`? | 003 OQ-3 | yes |
| [`probe_playlist_move.py`](probe_playlist_move.py) | Does `Move`'s `newIndex` refer to the list before or after removal? | 009 OQ-1 | yes |
| [`probe_playstate.py`](probe_playstate.py) | What does a playback-stopped report do to `UserData`? | 007 OQ-2 | yes |

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
```

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

Three of the four cannot answer their question without writing, and they say so rather than doing
it quietly: each refuses to run without `--allow-writes`.

| Probe | What it creates | Cleanup |
|---|---|---|
| `probe_sort_names.py` | 15 empty playlists with crafted names | Deletes them, including on failure |
| `probe_playlist_move.py` | 2 playlists | Deletes them, including on failure |
| `probe_playstate.py` | Play state on **one** item | Chooses an item with no user data, so restoring it is exact |

`probe_playstate.py` refuses to run at all if it cannot find a long item with no existing user
data. It will not overwrite a real resume position, because it could not put one back exactly.

### Planned

| Script | Purpose | Arrives with |
|---|---|---|
| `differential.py` | Issue the same request to Atrium and a real Jellyfin and compare field by field (L3) | Feature 010 |
| `probe_auth_mechanisms.py`, `probe_item_ids.py`, `probe_wire_format.py`, … | The remaining prior-measurement debts in [reference-target.md](../docs/compatibility/reference-target.md) | Their owning features |

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
