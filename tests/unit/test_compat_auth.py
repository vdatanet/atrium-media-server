# SPDX-License-Identifier: GPL-3.0-or-later
"""Where a token may arrive, and how the client header is spelled.

The two tables here are **measurements**, not preferences. Each row was issued against a live
Jellyfin 10.11.11 and carries the status it answered, so a change to the parser that made Atrium
kinder than the reference fails here rather than being discovered by a client that works against
one server and not the other.
`[probe: tools/probe_auth_mechanisms.py, Jellyfin 10.11.11, 2026-08-28]`

Pure functions over a request: no server, no database, no I/O.
"""

from __future__ import annotations

import pytest
from starlette.requests import Request

from atrium.compat.auth import (
    ClientInfo,
    client_info,
    extract_token,
    parse_client_authorization,
    parse_components,
    require_client_authorization,
)
from atrium.compat.errors import ClientAuthorizationError

TOKEN = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
BOGUS = "0" * 32


def build(headers: dict[str, str] | None = None, query: str = "") -> Request:
    """A request with exactly these headers and this query string, and nothing behind it."""
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/Users/Me",
            "query_string": query.encode("ascii"),
            "headers": [
                (name.lower().encode("ascii"), value.encode("utf-8"))
                for name, value in (headers or {}).items()
            ],
        }
    )


def emby(token: str = TOKEN, device_id: str = "device-1") -> str:
    return (
        f'MediaBrowser Client="Atrium Test", Device="Bench", '
        f'DeviceId="{device_id}", Token="{token}"'
    )


# --------------------------------------------------------------------------------------------
# The five mechanisms
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "label,headers,query",
    [
        ("X-Emby-Token header", {"X-Emby-Token": TOKEN}, ""),
        ("Authorization", {"Authorization": f'MediaBrowser Token="{TOKEN}"'}, ""),
        ("X-Emby-Authorization", {"X-Emby-Authorization": f'MediaBrowser Token="{TOKEN}"'}, ""),
        ("Authorization, with client info beside it", {"Authorization": emby()}, ""),
        ("X-Emby-Authorization, with client info beside it", {"X-Emby-Authorization": emby()}, ""),
        ("?ApiKey=", None, f"ApiKey={TOKEN}"),
        ("?api_key=", None, f"api_key={TOKEN}"),
    ],
)
def test_every_mechanism_presents_the_same_token(
    label: str, headers: dict[str, str] | None, query: str
) -> None:
    assert extract_token(build(headers, query)) == TOKEN, label


def test_x_emby_authorization_is_a_mechanism_the_specification_had_missed() -> None:
    """The fifth. It is the historical Emby form, and it authenticates against the reference.

    A server implementing only the four the specification listed would refuse a client that has
    worked against Jellyfin for years.
    """
    assert extract_token(build({"X-Emby-Authorization": emby()})) == TOKEN


def test_a_request_with_nothing_presents_nothing() -> None:
    assert extract_token(build()) is None
    assert extract_token(build({"Accept": "application/json"})) is None


def test_a_bearer_token_is_not_one_of_them() -> None:
    """`Bearer` is not a scheme the reference reads, and reading it would be a delta."""
    assert extract_token(build({"Authorization": f"Bearer {TOKEN}"})) is None


# --------------------------------------------------------------------------------------------
# Which one wins, measured pair by pair
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "label,headers,query,expected",
    [
        (
            "Authorization beats X-Emby-Authorization",
            {"Authorization": emby(TOKEN), "X-Emby-Authorization": emby(BOGUS)},
            "",
            TOKEN,
        ),
        (
            "...in both directions",
            {"Authorization": emby(BOGUS), "X-Emby-Authorization": emby(TOKEN)},
            "",
            BOGUS,
        ),
        (
            "X-Emby-Authorization beats X-Emby-Token",
            {"X-Emby-Authorization": emby(TOKEN), "X-Emby-Token": BOGUS},
            "",
            TOKEN,
        ),
        (
            "...in both directions",
            {"X-Emby-Authorization": emby(BOGUS), "X-Emby-Token": TOKEN},
            "",
            BOGUS,
        ),
        ("X-Emby-Token beats the query", {"X-Emby-Token": TOKEN}, f"ApiKey={BOGUS}", TOKEN),
        ("...in both directions", {"X-Emby-Token": BOGUS}, f"ApiKey={TOKEN}", BOGUS),
        ("ApiKey is read before api_key", None, f"ApiKey={TOKEN}&api_key={BOGUS}", TOKEN),
    ],
)
def test_two_tokens_resolve_the_way_the_reference_resolves_them(
    label: str, headers: dict[str, str] | None, query: str, expected: str
) -> None:
    """A client that sets a header once and builds URLs from a template sends two, and they
    disagree exactly when one of them is stale."""
    assert extract_token(build(headers, query)) == expected, label


# --------------------------------------------------------------------------------------------
# The grammar, one measured variation per row
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "label,value,accepted",
    [
        ("quoted values", f'MediaBrowser Client="p", DeviceId="d", Token="{TOKEN}"', True),
        ("unquoted values", f"MediaBrowser Client=p, DeviceId=d, Token={TOKEN}", True),
        ("no space after commas", f'MediaBrowser Client="p",DeviceId="d",Token="{TOKEN}"', True),
        ("a space before the comma", f'MediaBrowser Client="p" , Token="{TOKEN}"', True),
        ("two spaces after the scheme", f'MediaBrowser  Client="p", Token="{TOKEN}"', True),
        ("components reordered", f'MediaBrowser Token="{TOKEN}", Client="p", DeviceId="d"', True),
        ("an unknown component alongside", f'MediaBrowser Nonsense="x", Token="{TOKEN}"', True),
        ("a trailing comma", f'MediaBrowser Client="p", Token="{TOKEN}",', True),
        ("the Emby scheme", f'Emby Client="p", Token="{TOKEN}"', True),
        ("the scheme in any case", f'mediabrowser Client="p", Token="{TOKEN}"', True),
        ("no DeviceId at all", f'MediaBrowser Client="p", Token="{TOKEN}"', True),
        # The three the reference refuses. Atrium refuses them too - being kinder would let a
        # client be built against Atrium and fail against Jellyfin.
        ("spaces around the equals sign", f'MediaBrowser Client = "p", Token = "{TOKEN}"', False),
        ("a lowercase component name", f'MediaBrowser Client="p", token="{TOKEN}"', False),
        ("no scheme word at all", f'Client="p", Token="{TOKEN}"', False),
        ("a scheme nobody uses", f'Nonsense Client="p", Token="{TOKEN}"', False),
    ],
)
def test_the_grammar_matches_the_reference_row_for_row(
    label: str, value: str, accepted: bool
) -> None:
    found = extract_token(build({"X-Emby-Authorization": value}))
    assert (found == TOKEN) is accepted, label


def test_being_kinder_than_the_reference_would_be_the_delta() -> None:
    """`Token = x` is a 401 at the reference, so no working client sends it.

    Accepting it here would cost nothing today and would let somebody build a client against
    Atrium that fails against Jellyfin, which is the direction that matters. behaviours section 6.
    """
    assert parse_components(f'MediaBrowser Token = "{TOKEN}"') == {}
    assert extract_token(build({"X-Emby-Authorization": f'MediaBrowser Token = "{TOKEN}"'})) is None


# --------------------------------------------------------------------------------------------
# What the client said about itself
# --------------------------------------------------------------------------------------------


def test_the_four_components_are_read() -> None:
    info = parse_client_authorization(
        'MediaBrowser Client="Jellyfin Android", Device="Pixel 8", '
        'DeviceId="e5c0a1", Version="2.6.1"'
    )
    assert info == ClientInfo(
        client="Jellyfin Android", device="Pixel 8", device_id="e5c0a1", version="2.6.1"
    )


def test_a_quoted_value_may_contain_a_comma() -> None:
    """A device name is written by a person, and people put commas in things."""
    header = 'MediaBrowser Device="Joan\'s laptop, the old one", DeviceId="d"'
    info = parse_client_authorization(header)
    assert info is not None
    assert info.device == "Joan's laptop, the old one"


def test_an_unknown_component_is_ignored_rather_than_rejected() -> None:
    info = parse_client_authorization('MediaBrowser DeviceId="d", FromTheFuture="x"')
    assert info is not None
    assert info.device_id == "d"


def test_a_header_with_no_scheme_reads_as_nothing() -> None:
    assert parse_client_authorization('Client="p", DeviceId="d"') is None
    assert parse_client_authorization("") is None
    assert parse_client_authorization(None) is None


def test_the_token_stays_out_of_the_repr() -> None:
    """This object is built on every request, and is exactly what ends up in a debug log line."""
    info = parse_client_authorization(emby())
    assert info is not None
    assert info.token == TOKEN
    assert TOKEN not in repr(info)


def test_the_client_header_is_read_from_either_name(  # the two are one grammar
) -> None:
    assert client_info(build({"X-Emby-Authorization": emby()})) is not None
    assert client_info(build({"Authorization": emby()})) is not None
    assert client_info(build({"X-Emby-Token": TOKEN})) is None


# --------------------------------------------------------------------------------------------
# Where a missing DeviceId is fatal, and where it is not
# --------------------------------------------------------------------------------------------


def test_a_missing_device_id_is_not_fatal_in_general() -> None:
    """Measured: the reference answers 200 on an ordinary route for a header with no DeviceId.

    The plan called it "the one fatal case". It is fatal on one route, which is not the same
    thing, and a parser that raised would have refused requests the reference serves.
    """
    header = f'MediaBrowser Client="p", Token="{TOKEN}"'
    assert extract_token(build({"X-Emby-Authorization": header})) == TOKEN
    info = parse_client_authorization(header)
    assert info is not None
    assert info.device_id == ""


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        'Client="p", DeviceId="d"',
        f'MediaBrowser Client="p", Token="{TOKEN}"',
        'MediaBrowser Client="p", DeviceId=""',
    ],
)
def test_authentication_requires_a_device_id_and_refuses_without_one(value: str | None) -> None:
    """`POST /Users/AuthenticateByName` is where it is mandatory, and this is that rule."""
    with pytest.raises(ClientAuthorizationError):
        require_client_authorization(value)


def test_a_good_header_passes_the_authentication_rule() -> None:
    info = require_client_authorization(emby(device_id="e5c0a1"))
    assert info.device_id == "e5c0a1"
    assert info.token == TOKEN
