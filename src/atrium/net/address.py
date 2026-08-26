# SPDX-License-Identifier: GPL-3.0-or-later
"""The address this server tells a client to use.

`LocalAddress` in `/System/Info/Public` is what a client hands to another device - a cast target, a
second app, a download manager - so it has to be an address that *the requester* can reach, not
whichever one the server happens to like.

Three tiers, first match wins (specs/001-server-identity-and-discovery/spec.md section 3.4):

1. **A configured published URL**, verbatim. What an operator behind a reverse proxy sets, and it
   is never second-guessed: they know something the server does not.
2. **Derived from the request**, when configured to. The client's own `Host` and scheme, with the
   port omitted when it is the default for that scheme.
3. **Matched to the requester's network.** Which of this machine's addresses would reach that peer.

**Tier 3 asks the operating system rather than enumerating interfaces.** Opening a UDP socket
towards the peer and reading back the local address the kernel chose sends no packets, needs no
netmask arithmetic and no dependency - and it is *more* correct than matching prefixes by hand,
because it honours the real routing table. A requester arriving over a VPN gets the VPN-side
address for the same reason the kernel would use it.

**The reference's HTTPS override is deliberately absent.** It rewrites the scheme to HTTPS whenever
a certificate is configured, regardless of how the request arrived, which breaks clients handing
the address to a device with no TLS stack. See
docs/compatibility/behaviours.md section 4.2.
"""

from __future__ import annotations

import socket
from collections.abc import Callable
from typing import Final

from atrium.config.settings import NetworkSettings

#: Discard, per RFC 863. Nothing is sent - a UDP `connect` only fixes the socket's peer - but a
#: port that means "throw it away" is the right one to name if anything ever does.
_ROUTING_PROBE_PORT: Final = 9

DEFAULT_PORTS: Final = {"http": 80, "https": 443}

LOOPBACK_V4: Final = "127.0.0.1"


def address_facing(peer: str) -> str | None:
    """Which of this machine's addresses would reach `peer`, according to the routing table."""
    family = socket.AF_INET6 if ":" in peer else socket.AF_INET
    try:
        with socket.socket(family, socket.SOCK_DGRAM) as probe:
            probe.connect((peer, _ROUTING_PROBE_PORT))
            local: str = probe.getsockname()[0]
    except OSError:
        return None
    return local


def format_host(host: str) -> str:
    """Bracket an IPv6 literal, so it can carry a port."""
    return f"[{host}]" if ":" in host and not host.startswith("[") else host


def build_url(scheme: str, host: str, port: int | None) -> str:
    """`scheme://host[:port]`, omitting the port when it is the default for the scheme."""
    if port is None or DEFAULT_PORTS.get(scheme) == port:
        return f"{scheme}://{format_host(host)}"
    return f"{scheme}://{format_host(host)}:{port}"


def resolve_local_address(
    *,
    settings: NetworkSettings,
    request_host: str,
    request_scheme: str,
    request_port: int | None,
    client_address: str | None,
    lookup: Callable[[str], str | None] = address_facing,
) -> str:
    """The address to advertise for this request. Never empty."""
    # Tier 1. Returned exactly as written, minus a trailing slash.
    if settings.published_url:
        return settings.published_url.rstrip("/")

    # Tier 2. The client told us how it reached us; believe it.
    if settings.use_request_host:
        return build_url(request_scheme, request_host, request_port)

    # Tier 3. Ask the routing table which of our addresses faces this peer.
    #
    # The scheme comes from what this server actually serves, never from how the request arrived:
    # a request that reached us as HTTPS came through something else's TLS, and telling a client
    # to use HTTPS directly would send it somewhere that does not answer.
    host = lookup(client_address) if client_address else None
    return build_url("http", host or LOOPBACK_V4, settings.port)


__all__ = [
    "DEFAULT_PORTS",
    "LOOPBACK_V4",
    "address_facing",
    "build_url",
    "format_host",
    "resolve_local_address",
]
