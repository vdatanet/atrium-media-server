# SPDX-License-Identifier: GPL-3.0-or-later
"""Metadata resolution: local sources, remote providers, the merge, and the write path.

Feature 004. `metadata/` owns providers, merge and cache, and must not write the item table
directly (architecture section 1): `refresh.py` is the only caller of the write repository.
"""
