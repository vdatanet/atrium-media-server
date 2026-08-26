# tools

Scripts that keep the documentation honest. None of them is part of the server.

| Script | Purpose |
|---|---|
| [`fetch_reference_spec.py`](fetch_reference_spec.py) | Fetch and sanitise the Jellyfin OpenAPI document from a running server into the git-ignored `reference/` directory |
| [`extract_v1_surface.py`](extract_v1_surface.py) | Validate `docs/compatibility/surface.yaml` against that document — the automated half of Principle VI |

Planned, as the features that need them land:

| Script | Purpose | Arrives with |
|---|---|---|
| `differential.py` | Issue the same request to Atrium and a real Jellyfin and compare the responses field by field (L3) | Feature 010 |
| `probe_*.py` | One-off measurements against a running Jellyfin, each recording its version and date | As needed, per claim |

## Conventions

**Dependency-free.** These run in CI before any environment is built, so they use only the standard
library. `surface.yaml` is a deliberately flat subset of YAML for this reason.

**Probes record their own provenance.** Every `probe_*.py` prints the server version it measured
and the date, in the form the documentation cites
(`[probe: tools/probe_x.py, Jellyfin 10.11.11, YYYY-MM-DD]`). A measurement whose version is
unknown is not a measurement.

**Nothing here writes into the repository except by explicit flag.** Fetched reference material
goes to `reference/`, which is git-ignored.
