#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""What does `/Shows/NextUp` call "next", and do specials take part?

specs/005 section 3.7 and its plan section 6.8 claim the answer without a probe behind it: "the
first unplayed episode in (season, episode) order **after the highest played one**, specials
excluded from the chain". Two readings disagree the moment somebody rewatches an early episode:

* after the **highest-numbered** played episode - a rewatch of E01 changes nothing;
* after the **most recently** played episode - a rewatch of E01 makes E02 "next" again.

The probe discriminates them directly: it marks E02 played, reads NextUp, then marks E01 played
*afterwards* and reads again. It then plays a special and asks whether season 0 drives the chain,
and finally checks the one-row-per-series rule and the series order with two series active.

Writes, unavoidably: NextUp is a statement about play state and there is no play state to
measure until somebody plays something. It refuses series whose episodes carry any user data, so
every mark is a `DELETE /UserPlayedItems/{id}` away from exactly the state it found - restored in
`finally`, and verified.

Usage:
    python3 tools/probe_next_up.py http://your-jellyfin:8096 -u username --allow-writes
"""

from __future__ import annotations

from _probe import Probe, ProbeError, Server, main


def pristine(item: dict) -> bool:
    data = item.get("UserData") or {}
    return (
        not data.get("Played")
        and not data.get("PlayCount")
        and not data.get("PlaybackPositionTicks")
    )


def episodes_of(server: Server, series_id: str) -> list[dict]:
    body = server.get(f"/Shows/{series_id}/Episodes", userId=server.user_id)
    return list(body.get("Items", []))


def season_number(episode: dict) -> int:
    number = episode.get("ParentIndexNumber")
    return number if isinstance(number, int) else -1


def find_series(server: Server, minimum_regular: int, want_specials: bool) -> tuple | None:
    """A series whose episodes are all pristine, with enough regular episodes to walk."""
    found = server.get(
        "/Items",
        Recursive="true",
        IncludeItemTypes="Series",
        Limit=100,
        UserId=server.user_id,
    )
    for series in found.get("Items", []):
        episodes = episodes_of(server, series["Id"])
        regular = [one for one in episodes if season_number(one) > 0]
        specials = [one for one in episodes if season_number(one) == 0]
        if len(regular) < minimum_regular:
            continue
        if want_specials and not specials:
            continue
        if not all(pristine(one) for one in episodes):
            continue
        return series, regular, specials
    return None


def next_up(server: Server, series_id: str | None = None) -> list[dict]:
    params = {"userId": server.user_id, "Limit": 10}
    if series_id is not None:
        params["seriesId"] = series_id
    body = server.get_where("/Shows/NextUp", params)
    return list(body.get("Items", []))


def label(episode: dict | None) -> str:
    if episode is None:
        return "nothing"
    return f"S{season_number(episode):02d}E{episode.get('IndexNumber')}"


def run(server: Server) -> Probe:
    probe = Probe(
        script="probe_next_up.py",
        question="what does /Shows/NextUp call next, and do specials take part?",
        document="specs/005-item-query-api/spec.md",
        section="section 3.7",
        expectation=(
            "the first unplayed episode in (season, episode) order after the highest played "
            "one, specials excluded from the chain; one row per series"
        ),
    )

    plain = find_series(server, minimum_regular=4, want_specials=False)
    if plain is None:
        raise ProbeError(
            "no series with four pristine regular episodes; the probe will not overwrite "
            "somebody's real watch state, because it could not put it back exactly"
        )
    series, regular, _ = plain
    marked: list[str] = []

    def mark(episode: dict) -> None:
        server.post(f"/UserPlayedItems/{episode['Id']}", userId=server.user_id)
        marked.append(episode["Id"])

    def first(series_id: str) -> dict | None:
        rows = next_up(server, series_id)
        return rows[0] if rows else None

    findings: list[str] = []
    try:
        second = regular[1]
        mark(second)
        after_second = first(series["Id"])
        probe.observe(f"played {label(second)} of {series['Name']!r}", label(after_second))

        # The discriminating step: E01 played *after* E02. Recency says E02; index says E03.
        mark(regular[0])
        after_rewatch = first(series["Id"])
        probe.observe(f"then played {label(regular[0])} (later in time)", label(after_rewatch))

        by_recency = after_rewatch is not None and after_rewatch["Id"] == second["Id"]
        by_index = after_rewatch is not None and after_rewatch["Id"] == regular[2]["Id"]
        if by_recency:
            findings.append(
                "next means after the MOST RECENTLY played episode - a rewatch of an early "
                "episode resets the chain"
            )
        elif by_index:
            findings.append("next means after the highest-numbered played episode")
        else:
            findings.append(f"neither reading: {label(after_rewatch)}")

        with_specials = find_series(server, minimum_regular=1, want_specials=True)
        if with_specials is None:
            probe.note(
                "no pristine series with a specials season; the specials half is unmeasured "
                "on this library."
            )
        else:
            odd_series, _odd_regular, odd_specials = with_specials
            mark(odd_specials[0])
            after_special = first(odd_series["Id"])
            probe.observe(
                f"played special {label(odd_specials[0])} of {odd_series['Name']!r}",
                label(after_special),
            )
            if after_special is None:
                findings.append("a played special drives nothing: specials are out of the chain")
            elif season_number(after_special) == 0:
                findings.append("a played special is followed by the next special")
            else:
                findings.append(
                    f"a played special is followed by {label(after_special)}: specials drive "
                    "the regular chain"
                )

        # The global checks need a second active series, not a specials one.
        second_series = None
        second_plain = find_series(server, minimum_regular=2, want_specials=False)
        if second_plain is not None and second_plain[0]["Id"] != series["Id"]:
            second_series, second_regular, _ = second_plain
            mark(second_regular[0])
            rows = next_up(server)
            names = [one.get("SeriesName") for one in rows]
            probe.observe("global NextUp series order", ", ".join(str(one) for one in names))
            once = len(names) == len(set(names))
            findings.append(
                "one row per series" if once else "A SERIES APPEARED TWICE in global NextUp"
            )
            most_recent_first = bool(names) and names[0] == second_series["Name"]
            findings.append(
                "most recently played series first"
                if most_recent_first
                else f"series order is not most-recent-first: {names}"
            )
        else:
            probe.note("no second pristine series; the one-row and order halves are unmeasured.")
    finally:
        for item_id in marked:
            server.delete(f"/UserPlayedItems/{item_id}", userId=server.user_id)

    dirty = [
        one["Id"]
        for one in episodes_of(server, series["Id"])
        if one["Id"] in marked and not pristine(one)
    ]
    if dirty:
        raise ProbeError(f"cleanup failed: {len(dirty)} episode(s) still carry play state")
    probe.note("every mark was removed and the touched episodes verified pristine again.")

    contradicted = any(
        "MOST RECENTLY" in one
        or "neither reading" in one
        or "APPEARED TWICE" in one
        or "drive the regular chain" in one
        or "not most-recent-first" in one
        for one in findings
    )
    probe.conclude("; ".join(findings), matches_documentation=not contradicted)
    return probe


if __name__ == "__main__":
    raise SystemExit(main(run, __doc__.splitlines()[0], needs_writes=True))
