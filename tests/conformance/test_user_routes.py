# SPDX-License-Identifier: GPL-3.0-or-later
"""The five `/Users` routes, at the boundary a client sees.

Three acceptance criteria land here rather than in a unit test, because Principle VIII does not
accept a criterion proven against the function behind the route: **AC-2** (the refusals, compared
as bytes), **AC-5** (re-authenticating invalidates the previous token) and **AC-8** (a
configuration round-trips whole).
"""

from __future__ import annotations

import json
import re

import httpx
import pytest
from fastapi import FastAPI

from atrium.compat.guids import new_id
from atrium.db.repositories import UserRepository
from atrium.domain.user import User

PASSWORD = "correct horse battery staple"
CLIENT_HEADER = 'MediaBrowser Client="Atrium Test", Device="Bench", DeviceId="bench-1", Version="1"'
HEX32 = re.compile(r"\A[0-9a-f]{32}\Z")


def make_user(app: FastAPI, name: str = "Joan", **overrides: object) -> User:
    fields: dict[str, object] = {
        "id": new_id(),
        "name": name,
        "password_hash": app.state.passwords.hash(PASSWORD),
    }
    fields.update(overrides)
    with app.state.sessions.begin() as opened:
        return UserRepository(opened).add(User(**fields))  # type: ignore[arg-type]


async def log_in(
    client: httpx.AsyncClient, name: str = "Joan", password: str = PASSWORD, device: str = "bench-1"
) -> httpx.Response:
    header = CLIENT_HEADER.replace("bench-1", device)
    return await client.post(
        "/Users/AuthenticateByName",
        json={"Username": name, "Pw": password},
        headers={"X-Emby-Authorization": header},
    )


@pytest.fixture
def joan(app: FastAPI) -> User:
    return make_user(app)


# --------------------------------------------------------------------------------------------
# AC-1: authenticating
# --------------------------------------------------------------------------------------------


async def test_valid_credentials_answer_with_a_token_a_user_and_a_session(
    client: httpx.AsyncClient, joan: User
) -> None:
    answered = await log_in(client)
    assert answered.status_code == 200
    body = answered.json()

    assert HEX32.match(body["AccessToken"]), body["AccessToken"]
    assert body["User"]["Name"] == "Joan"
    assert body["SessionInfo"]["DeviceId"] == "bench-1"
    assert body["ServerId"] == body["User"]["ServerId"]


async def test_the_result_carries_the_reference_field_order(
    client: httpx.AsyncClient, joan: User
) -> None:
    """Measured. No client cares; a golden comparing bytes does, and so does a differential run."""
    body = json.loads((await log_in(client)).content)
    assert list(body) == ["User", "SessionInfo", "AccessToken", "ServerId"]
    assert list(body["User"]) == [
        "Name",
        "ServerId",
        "Id",
        "HasPassword",
        "HasConfiguredPassword",
        "HasConfiguredEasyPassword",
        "EnableAutoLogin",
        "LastLoginDate",
        "LastActivityDate",
        "Configuration",
        "Policy",
    ]


async def test_a_session_that_never_played_reports_the_dot_net_minimum_date(
    client: httpx.AsyncClient, joan: User
) -> None:
    """`0001-01-01T00:00:00.0000000Z`, not null and not absent. Measured."""
    body = (await log_in(client)).json()
    assert body["SessionInfo"]["LastPlaybackCheckIn"] == "0001-01-01T00:00:00.0000000Z"


async def test_the_token_authenticates_the_routes_that_need_one(
    client: httpx.AsyncClient, joan: User
) -> None:
    token = (await log_in(client)).json()["AccessToken"]
    assert (await client.get("/Users/Me", headers={"X-Emby-Token": token})).status_code == 200


# --------------------------------------------------------------------------------------------
# AC-2: the refusals, compared as bytes
# --------------------------------------------------------------------------------------------


async def test_an_unknown_username_is_401(client: httpx.AsyncClient, joan: User) -> None:
    assert (await log_in(client, name="nobody")).status_code == 401


async def test_a_wrong_password_is_401(client: httpx.AsyncClient, joan: User) -> None:
    assert (await log_in(client, password="wrong")).status_code == 401


async def test_a_disabled_account_is_403(app: FastAPI, client: httpx.AsyncClient) -> None:
    make_user(app, name="Gone", is_disabled=True)
    assert (await log_in(client, name="Gone")).status_code == 403


async def test_a_missing_client_header_is_400_and_specifically_not_401(
    client: httpx.AsyncClient, joan: User
) -> None:
    """A client reading this as `401` tells its user their password is wrong. It was not."""
    refused = await client.post(
        "/Users/AuthenticateByName", json={"Username": "Joan", "Pw": PASSWORD}
    )
    assert refused.status_code == 400


async def test_a_client_header_without_a_device_id_is_400(
    client: httpx.AsyncClient, joan: User
) -> None:
    refused = await client.post(
        "/Users/AuthenticateByName",
        json={"Username": "Joan", "Pw": PASSWORD},
        headers={"X-Emby-Authorization": 'MediaBrowser Client="x", Version="1"'},
    )
    assert refused.status_code == 400


async def test_the_refusals_differ_only_in_their_status(
    app: FastAPI, client: httpx.AsyncClient, joan: User
) -> None:
    """AC-2, as bytes. All three carry the reference's fixed 25-byte `text/plain` sentence, so a
    test that asserted status codes alone would pass against a server sending JSON."""
    make_user(app, name="Gone", is_disabled=True)

    unknown = await log_in(client, name="nobody")
    disabled = await log_in(client, name="Gone")
    broken = await client.post(
        "/Users/AuthenticateByName", json={"Username": "Joan", "Pw": PASSWORD}
    )

    assert [unknown.status_code, disabled.status_code, broken.status_code] == [401, 403, 400]
    for refusal in (unknown, disabled, broken):
        assert refusal.content == b"Error processing request."
        assert refusal.headers["content-type"] == "text/plain"


# --------------------------------------------------------------------------------------------
# AC-5: one device, one session
# --------------------------------------------------------------------------------------------


async def test_re_authenticating_invalidates_the_previous_token(
    client: httpx.AsyncClient, joan: User
) -> None:
    first = (await log_in(client)).json()["AccessToken"]
    assert (await client.get("/Users/Me", headers={"X-Emby-Token": first})).status_code == 200

    second = (await log_in(client)).json()["AccessToken"]
    assert first != second
    assert (await client.get("/Users/Me", headers={"X-Emby-Token": first})).status_code == 401
    assert (await client.get("/Users/Me", headers={"X-Emby-Token": second})).status_code == 200


async def test_a_second_device_keeps_its_own_session(client: httpx.AsyncClient, joan: User) -> None:
    phone = (await log_in(client, device="phone")).json()["AccessToken"]
    tablet = (await log_in(client, device="tablet")).json()["AccessToken"]
    assert (await client.get("/Users/Me", headers={"X-Emby-Token": phone})).status_code == 200
    assert (await client.get("/Users/Me", headers={"X-Emby-Token": tablet})).status_code == 200


# --------------------------------------------------------------------------------------------
# AC-8: the configuration round trip
# --------------------------------------------------------------------------------------------


async def test_a_configuration_round_trips_including_what_v1_does_not_act_on(
    client: httpx.AsyncClient, joan: User
) -> None:
    """AC-8. The properties v1 reads are two of sixteen; the other fourteen have to come back."""
    posted = {
        "AudioLanguagePreference": "cat",
        "DisplayMissingEpisodes": True,
        "SubtitleMode": "Smart",
        "CastReceiverId": "F007D4FE",
        "RememberAudioSelections": False,
        "OrderedViews": ["a" * 32, "b" * 32],
        "SomethingFromANewerServer": {"nested": [1, 2, 3]},
    }
    token = (await log_in(client)).json()["AccessToken"]
    stored = await client.post("/Users/Configuration", json=posted, headers={"X-Emby-Token": token})
    assert stored.status_code == 204
    assert stored.content == b""

    read_back = await client.get("/Users/Me", headers={"X-Emby-Token": token})
    assert read_back.json()["Configuration"] == posted


async def test_posting_a_configuration_replaces_rather_than_merges(
    client: httpx.AsyncClient, joan: User
) -> None:
    token = (await log_in(client)).json()["AccessToken"]
    headers = {"X-Emby-Token": token}
    await client.post("/Users/Configuration", json={"A": 1, "B": 2}, headers=headers)
    await client.post("/Users/Configuration", json={"B": 3}, headers=headers)
    assert (await client.get("/Users/Me", headers=headers)).json()["Configuration"] == {"B": 3}


async def test_configuration_needs_a_token(client: httpx.AsyncClient, joan: User) -> None:
    assert (await client.post("/Users/Configuration", json={})).status_code == 401


# --------------------------------------------------------------------------------------------
# /Users/Public
# --------------------------------------------------------------------------------------------


async def test_public_users_answers_without_a_token(client: httpx.AsyncClient, joan: User) -> None:
    listed = await client.get("/Users/Public")
    assert listed.status_code == 200
    assert [one["Name"] for one in listed.json()] == ["Joan"]


async def test_public_users_sends_the_whole_object_as_the_reference_does(
    client: httpx.AsyncClient, joan: User
) -> None:
    """Measured, and the opposite of what spec section 3.4 asserted.

    The reference sends `Configuration` and `Policy` to a caller with no token, byte-identical to
    the authenticated response. Replicated per Principle V; the argument, including the case for
    diverging, is behaviours section 3.5.
    """
    entry = (await client.get("/Users/Public")).json()[0]
    assert "Configuration" in entry
    assert "Policy" in entry
    assert entry["Policy"]["IsAdministrator"] is False


async def test_a_hidden_user_is_not_on_the_login_screen(
    app: FastAPI, client: httpx.AsyncClient, joan: User
) -> None:
    make_user(app, name="Ghost", is_hidden=True)
    assert [one["Name"] for one in (await client.get("/Users/Public")).json()] == ["Joan"]


async def test_every_user_hidden_is_an_empty_list_and_a_200(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    """AC-6's surviving half: an installation where every user is hidden legitimately returns []."""
    make_user(app, name="Ghost", is_hidden=True)
    listed = await client.get("/Users/Public")
    assert listed.status_code == 200
    assert listed.json() == []


# --------------------------------------------------------------------------------------------
# AC-7: who may read whom
# --------------------------------------------------------------------------------------------


async def test_a_user_may_always_read_themselves(client: httpx.AsyncClient, joan: User) -> None:
    token = (await log_in(client)).json()["AccessToken"]
    served = await client.get(f"/Users/{joan.id}", headers={"X-Emby-Token": token})
    assert served.status_code == 200
    assert served.json()["Id"] == joan.id


async def test_an_ordinary_user_reads_another_whole(
    app: FastAPI, client: httpx.AsyncClient, joan: User
) -> None:
    """This asserted a `403` until 2026-09-01. The reference answers `200`, with everything.

    The refusal was Atrium's own and spec section 3.7 stated it with no provenance; measured, an
    ordinary non-administrator naming another non-administrator is answered the whole section 3.5
    object, `Configuration` and `Policy` included
    `[probe: tools/probe_user_read.py, Jellyfin 10.11.11, 2026-09-01]`. Asserting the two
    properties rather than the status is the point: a `200` carrying a redacted object would be a
    different server from the one measured, and only the properties can tell them apart.
    """
    other = make_user(app, name="Ada")
    token = (await log_in(client)).json()["AccessToken"]
    served = await client.get(f"/Users/{other.id}", headers={"X-Emby-Token": token})
    assert served.status_code == 200
    body = served.json()
    assert body["Name"] == "Ada"
    assert "Configuration" in body
    assert body["Policy"]["IsAdministrator"] is False


async def test_a_non_administrator_reads_an_administrator_whole(
    app: FastAPI, client: httpx.AsyncClient, joan: User
) -> None:
    """The cell 009 T2 measured, and the one that makes this a disclosure rather than a widening.

    The bytes do not depend on who asked: a restricted non-administrator naming an administrator
    is answered exactly what that administrator reads of themselves, `Policy.IsAdministrator`
    included `[probe: tools/probe_user_read.py, Jellyfin 10.11.11, 2026-09-01]`.
    """
    admin = make_user(app, name="Root", is_administrator=True)
    elevated = (await log_in(client, name="Root", device="bench-2")).json()["AccessToken"]
    token = (await log_in(client)).json()["AccessToken"]
    served = await client.get(f"/Users/{admin.id}", headers={"X-Emby-Token": token})
    own = await client.get(f"/Users/{admin.id}", headers={"X-Emby-Token": elevated})
    assert served.status_code == 200
    assert served.json()["Policy"]["IsAdministrator"] is True

    # Everything but the two timestamps, which move because *asking* moves them: an
    # authenticated request advances `LastActivityDate` (AC-13), so two reads of one account can
    # never be byte-identical here whoever makes them. Every other property is the comparison
    # the probe made, and it found no redaction at all.
    moving = {"LastLoginDate", "LastActivityDate"}
    assert {k: v for k, v in served.json().items() if k not in moving} == {
        k: v for k, v in own.json().items() if k not in moving
    }


async def test_an_identifier_nobody_has_is_the_fourth_shape(
    client: httpx.AsyncClient, joan: User
) -> None:
    """`404`, the JSON-encoded bare string, and the same body whoever asks.

    Not the `403` this route used to send, and not the problem details every other `404` raised
    from a handler in this project answers: measured, `"User not found"` under
    `application/json; charset=utf-8`, identical for an administrator and for a non-administrator
    `[probe: tools/probe_user_read.py, Jellyfin 10.11.11, 2026-09-01]`.
    """
    token = (await log_in(client)).json()["AccessToken"]
    missing = await client.get(f"/Users/{new_id()}", headers={"X-Emby-Token": token})
    assert missing.status_code == 404
    assert missing.content == b'"User not found"'
    assert missing.headers["content-type"] == "application/json; charset=utf-8"


async def test_an_administrator_gets_the_same_body_for_an_identifier_nobody_has(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    make_user(app, name="Root", is_administrator=True)
    token = (await log_in(client, name="Root")).json()["AccessToken"]
    missing = await client.get(f"/Users/{new_id()}", headers={"X-Emby-Token": token})
    assert missing.status_code == 404
    assert missing.content == b'"User not found"'


async def test_a_malformed_identifier_is_the_validation_400(
    client: httpx.AsyncClient, joan: User
) -> None:
    """The model binder refuses it before the route runs, keyed on the parameter's own spelling.

    `{"userId": ["The value 'not-an-identifier' is not valid."]}`, measured
    `[probe: tools/probe_user_read.py, Jellyfin 10.11.11, 2026-09-01]` - which is why `userId` is
    typed as an identifier here rather than as a string.
    """
    token = (await log_in(client)).json()["AccessToken"]
    refused = await client.get("/Users/not-an-identifier", headers={"X-Emby-Token": token})
    assert refused.status_code == 400
    assert refused.json()["errors"] == {"userId": ["The value 'not-an-identifier' is not valid."]}
    # As bytes too, because the apostrophes are the part a parsed comparison cannot see: the
    # reference escapes them to the six-character `\\u0027` like every other quotable character
    # (behaviours 1.16), and this response class does it globally rather than by hand here.
    assert b"The value \\u0027not-an-identifier\\u0027 is not valid." in refused.content


async def test_reading_a_user_without_a_token_is_the_empty_401(
    app: FastAPI, client: httpx.AsyncClient, joan: User
) -> None:
    """`require_user` is the whole of this route's access rule, and it is the only refusal left."""
    refused = await client.get(f"/Users/{joan.id}")
    assert refused.status_code == 401
    assert refused.content == b""


async def test_an_administrator_reading_another_is_200(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    admin = make_user(app, name="Root", is_administrator=True)
    other = make_user(app, name="Ada")
    token = (await log_in(client, name="Root")).json()["AccessToken"]
    served = await client.get(f"/Users/{other.id}", headers={"X-Emby-Token": token})
    assert served.status_code == 200
    assert served.json()["Name"] == "Ada"
    assert admin.id != other.id


async def test_the_parameterised_route_does_not_swallow_the_literal_ones(
    client: httpx.AsyncClient, joan: User
) -> None:
    """`/users/public` is the public route, not a user whose identifier is `public`."""
    assert (await client.get("/users/public")).status_code == 200
    assert (await client.get("/users/public")).json()[0]["Name"] == "Joan"
