# SPDX-License-Identifier: GPL-3.0-or-later
"""The address a request is from, and whether that address is this machine.

**Until 014 the address came from uvicorn's own default**, applied by `uvicorn.run` around the
application: its `ProxyHeadersMiddleware`, believing `X-Forwarded-For` and `X-Forwarded-Proto` from
`127.0.0.1` alone. Nobody chose that, and no test here could see it, because every test builds the
application without uvicorn. That was harmless while the address only chose which of this
machine's addresses to advertise. It stops being harmless the moment a security rule rests on it:
014's setup window admits a caller with no token when the request is from this machine
(specs/014-first-time-setup/spec.md section 3.1).

So the resolution moves **inside** the application, as the same middleware with the trust list the
operator writes in `config.toml` (`network.trusted_proxies`, whose default is uvicorn's), and
`server.main` turns uvicorn's copy off. Applied twice, the second pass would read an address that
is already the forwarded one as though it were the peer, and believe the header again from it.

**The middleware is composed, not reimplemented.** `ClientAddressMiddleware` writes down the peer
exactly as the transport handed it over, and whether uvicorn's own matching trusts it - IPs,
networks and `"*"` alike - and only then lets `ProxyHeadersMiddleware` rewrite `client` and
`scheme`. Asking the resolver's own trust object, rather than matching the list again here, is what
keeps "was the header believed" and "was the header applied" one answer.

**What "believed" means is narrower than "the peer was trusted"**, and the difference is two
headers. The resolver reads `X-Forwarded-For` and nothing else that carries an address; a trusted
proxy that forwards the client in `Forwarded` or `X-Real-IP` alone has its address ignored, and the
request keeps the proxy's loopback address. Counting that as local would reopen the window to
everything behind a proxy configured the common way, so a forwarding header is believed only when
it is `X-Forwarded-For` from a trusted peer (plan section 6.1, amended 2026-09-14).

See specs/014-first-time-setup/plan.md section 6.1.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Sequence
from typing import Final, NamedTuple

from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

#: Every header a proxy puts a client's address in. Only the first is ever applied; the other two
#: are here so their presence can be noticed, which is all a proxy nobody declared leaves behind.
FORWARDING_HEADERS: Final = ("x-forwarded-for", "forwarded", "x-real-ip")

#: The one of them the resolution reads.
APPLIED_HEADER: Final = "x-forwarded-for"

#: Where the peer is written down, in the request's own state.
PEER_STATE_KEY: Final = "peer"


class Peer(NamedTuple):
    """The other end of the connection, before any header was believed."""

    host: str | None
    trusted: bool


class ClientAddressMiddleware:
    """Record the peer as it arrived, then resolve the client address from the trusted proxies."""

    def __init__(self, app: ASGIApp, trusted_proxies: Sequence[str]) -> None:
        # uvicorn types its ASGI callables with its own TypedDicts and Starlette with plain
        # mappings; the two are the same protocol, spelled twice.
        self._resolve = ProxyHeadersMiddleware(
            app,  # type: ignore[arg-type]
            trusted_hosts=list(trusted_proxies),
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            client = scope.get("client")
            host = client[0] if client else None
            peer = Peer(host=host, trusted=host in self._resolve.trusted_hosts)
            scope.setdefault("state", {})[PEER_STATE_KEY] = peer
        await self._resolve(scope, receive, send)  # type: ignore[arg-type]


def is_loopback(host: str | None) -> bool:
    """Whether `host` is loopback: `127.0.0.0/8`, `::1`, or IPv4 loopback mapped into IPv6.

    The mapped form is unwrapped by hand. A dual-stack socket reports an IPv4 client as
    `::ffff:127.0.0.1`, and `ipaddress` only calls that loopback from Python 3.13 on - on 3.12,
    which this server supports, the local client would be from elsewhere.
    """
    if not host:
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped.is_loopback
    return address.is_loopback


def is_this_machine(request: Request) -> bool:
    """Whether the request is from this machine, as 014 spec section 3.1 defines it.

    The resolved address is loopback, **and** no forwarding header arrived that the resolution did
    not believe: either none arrived at all, or the peer was a trusted proxy and forwarded the
    client in `X-Forwarded-For` - in which case the loopback address is the originating client's,
    not the proxy's.

    **A request with no recorded peer is not from this machine.** It means the middleware did not
    run, so nothing can say whether a header was believed, and the answer that fails is the closed
    one.
    """
    if request.client is None or not is_loopback(request.client.host):
        return False
    peer = request.scope.get("state", {}).get(PEER_STATE_KEY)
    if not isinstance(peer, Peer):
        return False
    forwarded = {name for name in FORWARDING_HEADERS if name in request.headers}
    if not forwarded:
        return True
    return peer.trusted and APPLIED_HEADER in forwarded


__all__ = [
    "FORWARDING_HEADERS",
    "PEER_STATE_KEY",
    "ClientAddressMiddleware",
    "Peer",
    "is_loopback",
    "is_this_machine",
]
