# SPDX-License-Identifier: GPL-3.0-or-later
"""Turning a path into what it says about the work.

**Pure**: paths in, structured results out, no filesystem access anywhere (003 plan section 3). That
is what lets `tests/corpus/naming.yaml` run as a plain table test with no fixtures on disk at all.

Nothing here raises on a name it does not understand. An unrecognised path is a result with a title
and nothing else, which is what plan section 5 requires - a scan that threw on a strange filename
would abort on somebody's real library rather than on ours.
"""

from atrium.library.naming.clean import CleanName, clean_name, from_text, is_tag

__all__ = ["CleanName", "clean_name", "from_text", "is_tag"]
