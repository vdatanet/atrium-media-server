# SPDX-License-Identifier: GPL-3.0-or-later
"""`LocalAddress`: three tiers, and a divergence that has to be visible in code.

No test here touches a real interface. The routing lookup is injected, so the table below is about
the rules rather than about whatever network the machine running it happens to be on.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from atrium.config.settings import NetworkSettings
from atrium.net.address import (
    LOOPBACK_V4,
    address_facing,
    build_url,
    resolve_local_address,
)


def resolve(
    settings: NetworkSettings,
    *,
    request_host: str = "media.example.com",
    request_scheme: str = "https",
    request_port: int | None = 443,
    client_address: str | None = "192.168.1.50",
    lookup: Callable[[str], str | None] = lambda _peer: "192.168.1.36",
) -> str:
    return resolve_local_address(
        settings=settings,
        request_host=request_host,
        request_scheme=request_scheme,
        request_port=request_port,
        client_address=client_address,
        lookup=lookup,
    )


# --------------------------------------------------------------------------------------------
# Tier 1 - a published URL is never second-guessed
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "configured",
    ["https://media.example.com", "https://media.example.com/", "https://media.example.com///"],
)
def test_a_published_url_is_returned_verbatim(configured: str) -> None:
    """Trailing slashes off, nothing else touched. The operator knows what the server does not."""
    assert resolve(NetworkSettings(published_url=configured)) == "https://media.example.com"


def test_a_published_url_beats_everything_else() -> None:
    settings = NetworkSettings(published_url="https://media.example.com", use_request_host=True)
    assert resolve(settings) == "https://media.example.com"


def test_a_published_url_with_a_path_keeps_it() -> None:
    """A reverse proxy may serve Atrium under a sub-path; rewriting that would break it."""
    settings = NetworkSettings(published_url="https://example.com/media")
    assert resolve(settings) == "https://example.com/media"


# --------------------------------------------------------------------------------------------
# Tier 2 - the client told us how it reached us
# --------------------------------------------------------------------------------------------


def test_the_request_host_is_used_when_configured() -> None:
    settings = NetworkSettings(use_request_host=True)
    assert resolve(settings) == "https://media.example.com"


@pytest.mark.parametrize(
    ("scheme", "port", "expected"),
    [
        ("http", 80, "http://media.example.com"),
        ("https", 443, "https://media.example.com"),
        ("http", 8096, "http://media.example.com:8096"),
        ("https", 8443, "https://media.example.com:8443"),
        ("http", None, "http://media.example.com"),
    ],
)
def test_the_default_port_is_omitted(scheme: str, port: int | None, expected: str) -> None:
    settings = NetworkSettings(use_request_host=True)
    assert resolve(settings, request_scheme=scheme, request_port=port) == expected


# --------------------------------------------------------------------------------------------
# Tier 3 - which of our addresses faces this requester
# --------------------------------------------------------------------------------------------


def test_two_requesters_on_two_networks_get_two_answers() -> None:
    """The whole reason this field is per-request rather than a constant."""
    settings = NetworkSettings(port=8096)
    routes = {"192.168.1.50": "192.168.1.36", "10.8.0.2": "10.8.0.1"}
    for peer, expected in routes.items():
        got = resolve(settings, client_address=peer, lookup=lambda p: routes[p])
        assert got == f"http://{expected}:8096"


def test_a_requester_matching_nothing_gets_loopback_not_an_empty_string() -> None:
    """A client receiving "" has no way to recover; one receiving a wrong address fails visibly."""
    settings = NetworkSettings(port=8096)
    assert resolve(settings, lookup=lambda _p: None) == f"http://{LOOPBACK_V4}:8096"


def test_an_unknown_client_address_gets_loopback() -> None:
    settings = NetworkSettings(port=8096)
    assert resolve(settings, client_address=None) == f"http://{LOOPBACK_V4}:8096"


def test_an_ipv6_address_is_bracketed() -> None:
    settings = NetworkSettings(port=8096)
    assert resolve(settings, lookup=lambda _p: "fe80::1") == "http://[fe80::1]:8096"


# --------------------------------------------------------------------------------------------
# The divergence, asserted in code and not only in prose
# --------------------------------------------------------------------------------------------


def test_the_advertised_scheme_does_not_follow_the_request() -> None:
    """behaviours 4.2, made structural.

    The reference rewrites this to HTTPS whenever a certificate is configured, regardless of how
    the request arrived - which breaks a client handing the address to a device with no TLS stack.

    In tier 3 the scheme comes from what this server actually serves. A request that reached us as
    HTTPS came through something else's TLS, and telling a client to use HTTPS directly would send
    it somewhere that does not answer.
    """
    settings = NetworkSettings(port=8096)
    assert resolve(settings, request_scheme="https").startswith("http://")


def test_there_is_no_certificate_path_that_could_override_it() -> None:
    """A divergence that only lives in a document is one refactor away from disappearing.

    Nothing in the settings can influence tier 3's scheme, which is what makes the absence
    structural rather than a decision someone has to keep making.
    """
    assert not any(
        "cert" in name.lower() or "tls" in name.lower() for name in NetworkSettings.model_fields
    )


# --------------------------------------------------------------------------------------------
# The routing lookup itself
# --------------------------------------------------------------------------------------------


def test_the_routing_lookup_answers_for_loopback() -> None:
    """The one peer whose answer is knowable on any machine, so the test is not machine-specific."""
    assert address_facing("127.0.0.1") == "127.0.0.1"


def test_the_routing_lookup_returns_none_rather_than_raising() -> None:
    """`.invalid` is reserved by RFC 6761 and must never resolve, anywhere.

    A bare `not-an-address` was the same test with a dependency hidden in it: a resolver with a
    search domain, or a provider that answers every name with its own advertising host, resolves
    it - and the test would then fail on somebody's laptop for a reason that has nothing to do
    with this function.
    """
    assert address_facing("atrium-does-not-exist.invalid") is None


def test_build_url_brackets_ipv6() -> None:
    assert build_url("http", "::1", 8096) == "http://[::1]:8096"
    assert build_url("http", "[::1]", 8096) == "http://[::1]:8096"
