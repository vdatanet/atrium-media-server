# SPDX-License-Identifier: GPL-3.0-or-later
"""The one HTTP door, sealed before anybody walks through it.

Every request this feature makes to somebody else's server goes through `RemoteAccess.get`. That
is the second of 004's two structural decisions (its task list says so out loud): both providers
arrive **behind** an already-tested limiter and cache, so no later task can write an unthrottled
loop against an API somebody has to pay for.

Three things are true of this module and of nothing else in `metadata/`:

* **It is the only place a client is constructed.** An import-direction test asserts it, which is
  what turns "no test reaches the network" from a discipline into a property. A provider module
  that wanted its own client would have to change that test to get it.
* **The transport is injected.** A test hands in a transport that answers from a recorded file and
  counts what it was asked for; nothing is patched and no socket is opened.
* **Rate is enforced against an injectable clock**, so a test can prove a bucket honours its rate
  in microseconds rather than by sleeping.

**The cache is not what makes AC-13 true.** A rescan of an unchanged library makes no requests
because 003's change detection means nothing asks (plan section 1). This cache exists for the two
cases where something *does* ask again: retrying after a provider was down, and a `Replace` refresh
that re-fetches deliberately.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import delete, select
from sqlalchemy.orm import Session as OrmSession

from atrium.compat.dates import utc_now
from atrium.db import models

logger = logging.getLogger(__name__)

#: How long a fetched payload stays fresh. Long, because metadata about a film from 1999 does not
#: move, and the cost of being a fortnight stale is an overview that is a fortnight old.
DEFAULT_TTL = timedelta(days=14)

#: How long the reader waits before deciding a provider is down. A scan blocked on one unreachable
#: host is worse than a scan that marks a few items pending and moves on (AC-8).
DEFAULT_TIMEOUT = 15.0


class ProviderUnavailableError(RuntimeError):
    """The provider could not be reached, or answered with something that is not an answer.

    Never a scan failure: the caller keeps whatever local metadata the item has and marks it
    `refresh_pending` (spec section 3.5 rule 4, AC-8).
    """


class RateLimitedError(ProviderUnavailableError):
    """A `429`. Distinct because the response to it is different: back off **and halve the bucket
    for the rest of the scan**, rather than simply retrying later."""


# ----------------------------------------------------------------------------------------------
# Rate
# ----------------------------------------------------------------------------------------------


@dataclass
class TokenBucket:
    """A provider's request budget, refilled continuously.

    A bucket rather than a sleep-between-calls because the shape of a scan is bursty: a hundred
    items resolve from local sources and ask nothing, then one asks three times. A bucket lets the
    burst through at the rate the provider published and holds the steady state at it.

    `sleep` and `now` are injected so a test can prove the rate without spending it. The default
    pair is the real one.
    """

    rate: float
    """Requests per second the provider permits. TMDB is 4; MusicBrainz is 1 (plan section 6.8)."""

    capacity: float = 0.0
    """How large a burst is allowed. Defaults to one second's worth, which is the honest reading of
    "N requests per second"."""

    now: Callable[[], float] = field(default_factory=lambda: _monotonic)
    sleep: Callable[[float], None] = field(default_factory=lambda: _sleep)

    _tokens: float = field(init=False, default=0.0)
    _last: float = field(init=False, default=0.0)

    def __post_init__(self) -> None:
        if self.rate <= 0:
            raise ValueError("a rate of zero would block for ever; disable the provider instead")
        if self.capacity <= 0:
            self.capacity = self.rate
        self._tokens = self.capacity
        self._last = self.now()

    def take(self) -> None:
        """Wait until a request may be made, then spend one token."""
        self._refill()
        if self._tokens < 1.0:
            self.sleep((1.0 - self._tokens) / self.rate)
            self._refill()
        self._tokens -= 1.0

    def halve(self) -> None:
        """A `429` means the published rate was not the real one. Halved for the rest of the
        scan rather than reset, because a bucket that recovers immediately asks to be told again.
        """
        self.rate = max(self.rate / 2.0, 0.05)
        self.capacity = max(self.capacity / 2.0, 1.0)
        self._tokens = 0.0
        logger.info("rate limited; bucket halved to %.3f requests/second", self.rate)

    def _refill(self) -> None:
        moment = self.now()
        elapsed = max(moment - self._last, 0.0)
        self._last = moment
        self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)


def _monotonic() -> float:
    import time

    return time.monotonic()


def _sleep(seconds: float) -> None:
    import time

    time.sleep(seconds)


# ----------------------------------------------------------------------------------------------
# The cache
# ----------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CacheEntry:
    payload: Any
    fetched_at: datetime
    expires_at: datetime | None


class ResponseCache:
    """`provider_cache`, as a get/put pair.

    **The rows promise nothing.** They are what somebody else's server said; dropping the table
    costs a refresh, not data - which is why this class has a `forget` and no migration story.
    """

    def __init__(self, session: OrmSession) -> None:
        self._session = session

    def get(
        self, provider: str, request_key: str, *, now: datetime | None = None
    ) -> CacheEntry | None:
        """The cached entry, or `None` for a miss **or an expiry**.

        The two are one answer on purpose: a caller that treated them differently would be
        deciding freshness twice.

        **An entry rather than a payload**, because a payload of `None` is a perfectly good
        answer - it is how a `404` is remembered - and returning it bare made a cached "this
        provider does not know that id" indistinguishable from a miss, so the request was made
        again every time. The one thing caching a 404 is for.
        """
        row = self._session.get(models.ProviderCacheEntry, (provider, request_key))
        if row is None:
            return None
        moment = now if now is not None else utc_now()
        if row.expires_at is not None and row.expires_at <= moment:
            return None
        return CacheEntry(payload=row.payload, fetched_at=row.fetched_at, expires_at=row.expires_at)

    def put(
        self,
        provider: str,
        request_key: str,
        payload: Any,
        *,
        ttl: timedelta | None = DEFAULT_TTL,
        now: datetime | None = None,
    ) -> None:
        """Store a payload. `ttl=None` means **never expires**.

        An identity looked up by id caches indefinitely: an id does not change meaning, so the
        answer to "what is TMDB 603" is the same next year (plan section 6.8).
        """
        moment = now if now is not None else utc_now()
        row = self._session.get(models.ProviderCacheEntry, (provider, request_key))
        expires = None if ttl is None else moment + ttl
        if row is None:
            self._session.add(
                models.ProviderCacheEntry(
                    provider=provider,
                    request_key=request_key,
                    payload=payload,
                    fetched_at=moment,
                    expires_at=expires,
                )
            )
        else:
            row.payload = payload
            row.fetched_at = moment
            row.expires_at = expires
        self._session.flush()

    def forget(self, provider: str, request_key: str) -> None:
        self._session.execute(
            delete(models.ProviderCacheEntry).where(
                models.ProviderCacheEntry.provider == provider,
                models.ProviderCacheEntry.request_key == request_key,
            )
        )
        self._session.flush()

    def count(self, provider: str | None = None) -> int:
        query = select(models.ProviderCacheEntry.request_key)
        if provider is not None:
            query = query.where(models.ProviderCacheEntry.provider == provider)
        return len(list(self._session.execute(query).scalars()))


# ----------------------------------------------------------------------------------------------
# Credentials
# ----------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProviderCredentials:
    """What an operator configured for one provider. Absent is the normal case.

    A missing key disables that provider with a reason (AC-9) rather than failing a scan: a v1
    install with no internet must produce a usable library (spec section 3.5 rule 5).
    """

    api_key: str = ""
    contact: str = ""
    """An email or URL for the identifying `User-Agent` MusicBrainz requires (plan section 6.6)."""

    def __bool__(self) -> bool:
        return bool(self.api_key or self.contact)


# ----------------------------------------------------------------------------------------------
# The door
# ----------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Response:
    """What came back, already decoded, and whether it came from the cache."""

    payload: Any
    cached: bool = False


class RemoteAccess:
    """One provider's access to the network: its bucket, its cache, its credentials, its client.

    Constructed once per scan and passed to the provider modules, which never build one of their
    own. `transport` is `httpx`'s own seam: a test hands in one that answers from recorded bytes,
    and no socket is opened by anything.
    """

    def __init__(
        self,
        provider: str,
        *,
        session: OrmSession,
        base_url: str,
        rate: float,
        credentials: ProviderCredentials | None = None,
        headers: Mapping[str, str] | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.provider = provider
        self.credentials = credentials or ProviderCredentials()
        self.bucket = TokenBucket(
            rate=rate,
            now=clock or _monotonic,
            sleep=sleep or _sleep,
        )
        self._cache = ResponseCache(session)
        self._client = httpx.Client(
            base_url=base_url,
            headers=dict(headers or {}),
            timeout=timeout,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> RemoteAccess:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def get(
        self,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        ttl: timedelta | None = DEFAULT_TTL,
        bypass_cache: bool = False,
    ) -> Response:
        """One request, through the cache and the bucket, in that order.

        `bypass_cache` is what `Replace` sets: it re-fetches and **refills** the entry rather than
        ignoring it, so the next default refresh benefits from what the deliberate one paid for.

        Raises `ProviderUnavailableError` for anything that is not an answer. The caller keeps the
        item's local metadata and marks it pending; nothing is ever blanked because a network call
        failed (AC-8).
        """
        key = _request_key(path, params)
        if not bypass_cache:
            cached = self._cache.get(self.provider, key)
            if cached is not None:
                return Response(payload=cached.payload, cached=True)

        # **After the cache, before the request.** A cache hit costs no tokens, which is what
        # makes a retry of a partly-cached refresh cheap rather than a second full budget.
        self.bucket.take()

        try:
            reply = self._client.get(path, params=dict(params or {}))
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(f"{self.provider}: {exc}") from exc

        if reply.status_code == httpx.codes.TOO_MANY_REQUESTS:
            self.bucket.halve()
            raise RateLimitedError(f"{self.provider}: rate limited")
        if reply.status_code >= httpx.codes.INTERNAL_SERVER_ERROR:
            raise ProviderUnavailableError(f"{self.provider}: HTTP {reply.status_code}")
        if reply.status_code == httpx.codes.NOT_FOUND:
            # A 404 is an **answer**: this provider does not know that id. Cached like any other,
            # because asking again tomorrow gets the same answer and costs a request.
            payload = None
        elif reply.status_code >= httpx.codes.BAD_REQUEST:
            raise ProviderUnavailableError(f"{self.provider}: HTTP {reply.status_code}")
        else:
            try:
                payload = reply.json()
            except (json.JSONDecodeError, ValueError) as exc:
                raise ProviderUnavailableError(f"{self.provider}: not JSON: {exc}") from exc

        self._cache.put(self.provider, key, payload, ttl=ttl)
        return Response(payload=payload, cached=False)

    def get_bytes(self, url: str, *, max_bytes: int) -> bytes | None:
        """Raw bytes from an absolute URL - an image, and nothing else so far.

        **Through the bucket, past the cache.** Through the bucket because it is a request to
        somebody else's server and the rate is the rate; past the cache because `provider_cache`
        is a JSON column and a poster is two megabytes of it. Re-downloading is prevented by the
        content tag instead: a refresh that finds the image already present by tag never calls
        this at all (plan section 6.5).

        `None` when the reply is not an image-shaped success. Over `max_bytes` is a warning the
        caller raises, not a truncation: half a poster is worse than none.
        """
        self.bucket.take()
        try:
            reply = self._client.get(url, follow_redirects=True)
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(f"{self.provider}: {exc}") from exc

        if reply.status_code == httpx.codes.TOO_MANY_REQUESTS:
            self.bucket.halve()
            raise RateLimitedError(f"{self.provider}: rate limited")
        if reply.status_code != httpx.codes.OK:
            return None
        raw = reply.content
        return raw if len(raw) <= max_bytes else raw[: max_bytes + 1]


def _request_key(path: str, params: Mapping[str, str] | None) -> str:
    """What identifies a request within one provider.

    Sorted, so two callers that built the same query in different orders share one entry - and
    stable, so an entry written by one build is found by the next.
    """
    if not params:
        return path
    query = "&".join(f"{name}={params[name]}" for name in sorted(params))
    return f"{path}?{query}"


__all__ = [
    "DEFAULT_TIMEOUT",
    "DEFAULT_TTL",
    "CacheEntry",
    "ProviderCredentials",
    "ProviderUnavailableError",
    "RateLimitedError",
    "RemoteAccess",
    "Response",
    "ResponseCache",
    "TokenBucket",
]
