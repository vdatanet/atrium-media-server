# SPDX-License-Identifier: GPL-3.0-or-later
"""The wire contract: PascalCase, ticks, .NET dates, GUID formatting, auth header parsing.

This is the only package allowed to care that the wire format is Jellyfin's, which is what makes
the conformance sweeps enforceable rather than aspirational. It must not know that any specific
endpoint exists, and it must not import from `atrium.api`.
"""
