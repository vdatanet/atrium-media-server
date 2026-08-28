# SPDX-License-Identifier: GPL-3.0-or-later
"""Image bytes: finding them, transforming them, caching them.

`architecture.md` section 3 reserved this package in the layout from the start and feature 006
fills it. The boundary is the point: **`images/` owns bytes and knows nothing about HTTP**
(006 plan section 3). A header, a status code or a query parameter in here belongs in
`api/images.py`; a decision about which file to open or how large to make it belongs here.
"""
