# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the three guarantees that are invisible in a response.

A password reaching a log, a login whose duration says whether a username exists, and a failure
path that skips the KDF are all things a client cannot see and a reviewer cannot spot by reading.
They get their own directory because they are asserted differently from everything else here:
by capturing side effects rather than by comparing bytes.
"""

from __future__ import annotations
