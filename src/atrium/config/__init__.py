# SPDX-License-Identifier: GPL-3.0-or-later
"""Where things live on disk, what the operator set, and what the server persists.

`config.toml` is edited by a human and never written by the server. `state.json` is written by the
server and never edited by hand. See specs/001-server-identity-and-discovery/plan.md section 4.
"""
