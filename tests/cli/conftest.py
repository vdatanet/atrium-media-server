# SPDX-License-Identifier: GPL-3.0-or-later
"""The server `atrium-admin` is pointed at in these tests.

**Built through `atrium.server.create_app` looked up when the fixture runs**, never through the
shared `app` fixture: `tests/conftest.py` records the suite's requests for the L2 coverage check by
replacing that attribute, and a request to an application built from the name `conftest.py` bound
earlier reaches no recorder (014 T7, 2026-09-14).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI

from atrium import server as atrium_server
from atrium.config.paths import DataPaths
from atrium.library.scanner import Scanner
from tests.conftest import not_media


@pytest.fixture
async def server(paths: DataPaths) -> AsyncIterator[FastAPI]:
    """A server nobody has set up, whose scanner is handed the fixture tree's prober
    (`tests/conftest.py`'s `not_media`), stopped afterwards - `library add` starts a scan."""
    app = atrium_server.create_app(paths)
    app.state.readiness.mark_ready()
    app.state.scanner = Scanner(
        app.state.sessions, app.state.settings, app.state.paths, prober=not_media
    )
    yield app
    await app.state.scanner.stop()
