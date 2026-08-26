# SPDX-License-Identifier: GPL-3.0-or-later
"""HTTP routing: one module per reference controller.

Owns route registration, request parsing and status codes. Must not contain business rules or
touch the database directly. See docs/architecture.md section 1.
"""
