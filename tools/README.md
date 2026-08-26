# tools

Scripts that keep the documentation honest. None of them is part of the server.

## Reference material

| Script | Purpose |
|---|---|
| [`fetch_reference_spec.py`](fetch_reference_spec.py) | Fetch and sanitise the Jellyfin OpenAPI document from a running server into the git-ignored `reference/` directory |
| [`extract_v1_surface.py`](extract_v1_surface.py) | Validate `docs/compatibility/surface.yaml` against that document — the automated half of Principle VI |

## Probes

A probe answers **one** question about how a real Jellyfin behaves, prints its finding together
with the citation the documentation uses, and **exits non-zero when the finding contradicts what
this repository currently claims**. That last property is what makes them a regression suite for
the project's *beliefs*, not only for its code: when a server upgrade changes a behaviour, the
probe says so instead of the documentation quietly becoming false.

Specified in [specs/010 §3.5](../specs/010-conformance-harness/spec.md).

| Script | Question | Answers | Writes |
|---|---|---|---|
| [`probe_query_envelope.py`](probe_query_envelope.py) | What shape does each list endpoint return? | 005 OQ-6 | no |
| [`probe_sort_names.py`](probe_sort_names.py) | How does the server derive `SortName` from `Name`? | 003 OQ-3 | yes |
| [`probe_playlist_move.py`](probe_playlist_move.py) | Does `Move`'s `newIndex` refer to the list before or after removal? | 009 OQ-1 | yes |
| [`probe_playstate.py`](probe_playstate.py) | What does a playback-stopped report do to `UserData`? | 007 OQ-2 | yes |

### Running them

```bash
export JELLYFIN_PASSWORD='…'          # or omit and be prompted; --password is discouraged
S=http://your-jellyfin:8096

python3 tools/probe_query_envelope.py $S -u username
python3 tools/probe_sort_names.py     $S -u username --allow-writes
python3 tools/probe_playlist_move.py  $S -u username --allow-writes
python3 tools/probe_playstate.py      $S -u username --allow-writes
```

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
