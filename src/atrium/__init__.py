# SPDX-License-Identifier: GPL-3.0-or-later
"""Atrium: a media server that speaks the Jellyfin API.

Two version numbers exist in this project and confusing them is a bug in both directions.

`__version__` is Atrium's own. It appears in the `Server` response header, in logs, and in
`--version`. It is what a human reads.

`REFERENCE_VERSION` is the Jellyfin version whose API this server implements. It appears in the
`Version` field of the API's own responses, because clients gate their behaviour on it. It moves
only through the procedure in docs/compatibility/conformance.md, never as a side effect of
releasing Atrium.

See docs/compatibility/reference-target.md for why Atrium identifies itself one way to clients and
another way to people.
"""

__version__ = "0.1.0.dev0"

#: The Jellyfin API version this server implements. Pinned by ADR-0004.
REFERENCE_VERSION = "10.11.11"

#: The value of `ProductName` in API responses. It must be exactly this: multi-server clients use
#: it to decide which dialect they are speaking, and reading anything else sends them down an
#: unknown-server path. docs/compatibility/reference-target.md section 4.
REFERENCE_PRODUCT_NAME = "Jellyfin Server"

__all__ = ["REFERENCE_PRODUCT_NAME", "REFERENCE_VERSION", "__version__"]
