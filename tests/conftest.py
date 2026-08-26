# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared fixtures.

Every test gets a fresh instance with a temporary data directory: no shared state between tests,
no ordering dependencies, and the whole suite runs with no network and no external service
(Principle VII). See specs/001-server-identity-and-discovery/plan.md section 8.4.
"""

from __future__ import annotations
