# SPDX-License-Identifier: GPL-3.0-or-later
"""`/Startup` at the boundary a client sees: 014 AC-1 to AC-4.

Every request here is **from this machine, during setup** unless it says otherwise, because that is
the one caller the window admits with nothing to sign in with - and it is said, through
`test_setup_window.ask`, which will not send a request without an address. What the window admits
and refuses is that module's subject; this one is what the three routes then do.

The three `400` bodies are compared as bytes and content types, because they are three different
error shapes on one route (spec section 3.3) and a status code is the part they share.
"""

from __future__ import annotations

import getpass
import json
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from atrium.compat.errors import CONTROLLER_ERROR_BODY, NOT_FOUND_TITLE, PROBLEM_TYPE_NOT_FOUND
from atrium.config.paths import ConfigurationError, DataPaths
from atrium.config.state import SETUP_RECORDED
from atrium.db.repositories import UserRepository
from atrium.server import create_app
from atrium.users.first_account import FIRST_ACCOUNT_NAME, REMOTE_CONTROL_OF_OTHER_USERS
from tests.conformance.test_setup_window import (
    ELSEWHERE,
    LOOPBACK,
    PASSWORD,
    ask,
    make_account,
    sign_in,
    token_for,
)
from tests.conftest import data_dir

pytestmark = pytest.mark.conformance

JSON_TYPE = "application/json; charset=utf-8"


def built(paths: DataPaths) -> FastAPI:
    app = create_app(paths)
    app.state.readiness.mark_ready()
    return app


async def wizard_completed(app: FastAPI) -> bool:
    answered = await ask(app, ELSEWHERE, "GET", "/System/Info/Public")
    assert answered.status_code == 200
    value: bool = answered.json()["StartupWizardCompleted"]
    return value


async def first_user(app: FastAPI) -> httpx.Response:
    return await ask(app, LOOPBACK, "GET", "/Startup/User")


async def update(app: FastAPI, body: object) -> httpx.Response:
    return await ask(app, LOOPBACK, "POST", "/Startup/User", json=body)


def accounts(app: FastAPI) -> list[str]:
    with app.state.sessions.begin() as opened:
        return [one.name for one in UserRepository(opened).all()]


# --------------------------------------------------------------------------------------------
# AC-1: StartupWizardCompleted, and that it survives
# --------------------------------------------------------------------------------------------


async def test_ac1_a_fresh_server_is_unfinished_and_complete_finishes_it_across_a_restart(
    tmp_path: Path,
) -> None:
    paths = data_dir(tmp_path / "atrium")
    before = built(paths)
    assert await wizard_completed(before) is False

    assert (await ask(before, LOOPBACK, "POST", "/Startup/Complete")).status_code == 204
    assert await wizard_completed(before) is True
    before.state.db.dispose()

    after = built(paths)
    assert await wizard_completed(after) is True
    # And the window is closed across the restart, not only the flag.
    assert (await first_user(after)).status_code == 401


def _as_written_before_setup_existed(paths: DataPaths) -> None:
    raw = json.loads(paths.state_file.read_text(encoding="utf-8"))
    del raw[SETUP_RECORDED]
    paths.state_file.write_text(json.dumps(raw), encoding="utf-8")


async def test_ac1_a_server_that_held_an_account_before_this_feature_starts_finished(
    tmp_path: Path,
) -> None:
    """Otherwise any process on the machine could set that account's password (spec 3.1)."""
    paths = data_dir(tmp_path / "atrium")
    old = built(paths)
    make_account(old, "Joan", administrator=True)
    old.state.db.dispose()
    _as_written_before_setup_existed(paths)

    upgraded = built(paths)

    assert await wizard_completed(upgraded) is True
    assert (await update(upgraded, {"Password": "stolen"})).status_code == 401
    assert (await sign_in(upgraded, ELSEWHERE, "Joan")).status_code == 200


async def test_ac1_a_server_that_held_no_account_before_this_feature_starts_unfinished(
    tmp_path: Path,
) -> None:
    paths = data_dir(tmp_path / "atrium")
    built(paths).state.db.dispose()
    _as_written_before_setup_existed(paths)

    upgraded = built(paths)

    assert await wizard_completed(upgraded) is False
    assert (await first_user(upgraded)).status_code == 200


async def test_ac1_a_restart_in_the_middle_of_setup_keeps_the_window_open(tmp_path: Path) -> None:
    """An account and the flag `false`, in a file this build wrote, is not an old install."""
    paths = data_dir(tmp_path / "atrium")
    during = built(paths)
    assert (await first_user(during)).status_code == 200
    during.state.db.dispose()

    restarted = built(paths)

    assert await wizard_completed(restarted) is False
    assert (await update(restarted, {"Password": PASSWORD})).status_code == 204


# --------------------------------------------------------------------------------------------
# AC-2: GET /Startup/User creates the first account
# --------------------------------------------------------------------------------------------


async def test_ac2_the_read_creates_one_hidden_administrator_and_answers_its_name(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`MyJellyfinUser` whatever account the process runs as - here, a valid username."""
    monkeypatch.setattr(getpass, "getuser", lambda: "joan")
    monkeypatch.setenv("USER", "joan")
    monkeypatch.setenv("USERNAME", "joan")

    answered = await first_user(app)

    assert answered.status_code == 200
    assert answered.headers["content-type"] == JSON_TYPE
    assert answered.content == b'{"Name":"MyJellyfinUser"}'
    with app.state.sessions.begin() as opened:
        (account,) = UserRepository(opened).all()
    assert account.name == FIRST_ACCOUNT_NAME
    assert account.is_administrator is True
    assert account.is_hidden is True
    assert account.enable_content_deletion is True
    assert account.policy_extra == {REMOTE_CONTROL_OF_OTHER_USERS: True}
    assert account.password_hash is None


async def test_ac2_the_first_account_is_hidden_from_the_sign_in_screen(app: FastAPI) -> None:
    assert (await first_user(app)).status_code == 200
    public = await ask(app, ELSEWHERE, "GET", "/Users/Public")
    assert public.status_code == 200
    assert public.json() == []


async def test_ac2_a_second_read_creates_nothing(app: FastAPI) -> None:
    first = await first_user(app)
    second = await first_user(app)
    assert first.content == second.content
    assert accounts(app) == [FIRST_ACCOUNT_NAME]


async def test_ac2_the_read_answers_the_first_account_when_one_exists(app: FastAPI) -> None:
    """Inserted first, not first by name: `Zed` before `Abel` is `Zed`."""
    make_account(app, "Zed", administrator=True)
    make_account(app, "Abel", administrator=False)
    assert (await first_user(app)).json() == {"Name": "Zed"}
    assert sorted(accounts(app)) == ["Abel", "Zed"]


async def test_ac2_a_read_that_loses_the_race_to_create_answers_the_winners_account(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two first reads at once: the loser's insert breaks the unique name and it reads again."""
    from sqlalchemy.exc import IntegrityError

    import atrium.users.first_account as first_account

    def lose(repository: UserRepository) -> object:
        make_account(app, "Winner", administrator=True)
        raise IntegrityError("INSERT INTO users", {}, Exception("UNIQUE constraint failed"))

    monkeypatch.setattr(first_account, "ensure_first_account", lose)

    answered = await first_user(app)

    assert answered.status_code == 200
    assert answered.json() == {"Name": "Winner"}
    assert accounts(app) == ["Winner"]


# --------------------------------------------------------------------------------------------
# AC-3: POST /Startup/User
# --------------------------------------------------------------------------------------------


async def test_ac3_no_account_is_404_in_problem_details(app: FastAPI) -> None:
    answered = await update(app, {"Name": "Joan", "Password": PASSWORD})

    assert answered.status_code == 404
    assert answered.headers["content-type"] == JSON_TYPE
    body = answered.json()
    assert list(body) == ["type", "title", "status", "traceId"]
    assert body["type"] == PROBLEM_TYPE_NOT_FOUND
    assert body["title"] == NOT_FOUND_TITLE
    assert body["status"] == 404
    assert accounts(app) == []


async def test_ac3_the_read_then_makes_the_update_possible(app: FastAPI) -> None:
    """The order is part of the contract: `404` before the read, `204` after it."""
    assert (await update(app, {"Password": PASSWORD})).status_code == 404
    assert (await first_user(app)).status_code == 200
    assert (await update(app, {"Password": PASSWORD})).status_code == 204


@pytest.mark.parametrize(
    "body",
    [
        {"Name": "Joan", "Password": ""},
        {"Name": "Joan", "Password": "   "},
        {"Name": "Joan", "Password": "\t\n"},
        {"Name": "Joan", "Password": None},
        {"Name": "Joan"},
        {},
    ],
    ids=["empty", "spaces", "tab and newline", "null", "missing", "empty body"],
)
async def test_ac3_a_blank_password_is_400_as_a_bare_json_string(
    app: FastAPI, body: dict[str, object]
) -> None:
    """And nothing is renamed: the password is checked before the name (plan section 6.4)."""
    assert (await first_user(app)).status_code == 200

    answered = await update(app, body)

    assert answered.status_code == 400
    assert answered.headers["content-type"] == JSON_TYPE
    assert answered.content == b'"Password must not be empty"'
    assert accounts(app) == [FIRST_ACCOUNT_NAME]


async def test_ac3_a_blank_password_on_a_server_with_no_account_is_still_404(app: FastAPI) -> None:
    assert (await update(app, {"Password": ""})).status_code == 404


@pytest.mark.parametrize("name", ["", " ", "bad/name:here", " Joan", "Joan "])
async def test_ac3_an_invalid_name_is_400_and_keeps_the_name_and_the_password(
    app: FastAPI, name: str
) -> None:
    """T1's reading: a refused rename leaves the password as it was, not only the name."""
    assert (await first_user(app)).status_code == 200
    assert (await update(app, {"Password": PASSWORD})).status_code == 204

    answered = await update(app, {"Name": name, "Password": "a password nobody set"})

    assert answered.status_code == 400
    assert answered.headers["content-type"] == "text/plain"
    assert answered.content == CONTROLLER_ERROR_BODY
    assert accounts(app) == [FIRST_ACCOUNT_NAME]
    assert (await sign_in(app, ELSEWHERE, FIRST_ACCOUNT_NAME, PASSWORD)).status_code == 200
    refused = await sign_in(app, ELSEWHERE, FIRST_ACCOUNT_NAME, "a password nobody set")
    assert refused.status_code == 401


async def test_ac3_a_name_another_account_holds_is_400_and_keeps_the_name_and_the_password(
    app: FastAPI,
) -> None:
    """Compared ignoring case, as a sign-in is."""
    assert (await first_user(app)).status_code == 200
    assert (await update(app, {"Password": PASSWORD})).status_code == 204
    make_account(app, "Joan", administrator=False)

    answered = await update(app, {"Name": "JOAN", "Password": "a password nobody set"})

    assert answered.status_code == 400
    assert answered.headers["content-type"] == "text/plain"
    assert answered.content == CONTROLLER_ERROR_BODY
    assert sorted(accounts(app)) == ["Joan", FIRST_ACCOUNT_NAME]
    assert (await sign_in(app, ELSEWHERE, FIRST_ACCOUNT_NAME, PASSWORD)).status_code == 200


async def test_ac3_an_update_renames_sets_the_password_and_the_account_signs_in(
    app: FastAPI,
) -> None:
    assert (await first_user(app)).status_code == 200

    answered = await update(app, {"Name": "Joan", "Password": PASSWORD})

    assert answered.status_code == 204
    assert answered.content == b""
    assert accounts(app) == ["Joan"]
    assert (await first_user(app)).json() == {"Name": "Joan"}
    signed_in = await sign_in(app, ELSEWHERE, "Joan", PASSWORD)
    assert signed_in.status_code == 200
    assert signed_in.json()["User"]["Policy"]["IsAdministrator"] is True
    assert (await sign_in(app, ELSEWHERE, FIRST_ACCOUNT_NAME, PASSWORD)).status_code == 401


async def test_ac3_a_name_differing_only_in_case_is_not_a_rename(app: FastAPI) -> None:
    assert (await first_user(app)).status_code == 200
    assert (await update(app, {"Name": "myjellyfinuser", "Password": PASSWORD})).status_code == 204
    assert accounts(app) == [FIRST_ACCOUNT_NAME]


async def test_ac3_no_name_sets_the_password_alone(app: FastAPI) -> None:
    assert (await first_user(app)).status_code == 200
    assert (await update(app, {"Password": PASSWORD})).status_code == 204
    assert accounts(app) == [FIRST_ACCOUNT_NAME]
    assert (await sign_in(app, ELSEWHERE, FIRST_ACCOUNT_NAME, PASSWORD)).status_code == 200


async def test_ac3_property_names_bind_in_any_case(app: FastAPI) -> None:
    assert (await first_user(app)).status_code == 200
    assert (await update(app, {"name": "Joan", "password": PASSWORD})).status_code == 204
    assert (await sign_in(app, ELSEWHERE, "Joan", PASSWORD)).status_code == 200


async def test_ac3_a_request_with_no_json_body_is_the_content_type_refusal(app: FastAPI) -> None:
    """The body is required, so nothing readable is behaviours section 1.11's fifth shape.

    Declared exactly as the three reporting routes whose `415` was measured - a non-nullable
    body parameter under nullable reference types - `[source:
    Jellyfin.Api/Controllers/StartupController.cs:132 and PlaystateController.cs:201 @ v10.11.11]`,
    and not measured on this route itself.
    """
    assert (await first_user(app)).status_code == 200
    answered = await ask(app, LOOPBACK, "POST", "/Startup/User")
    assert answered.status_code == 415
    assert answered.json()["title"] == "Unsupported Media Type"


# --------------------------------------------------------------------------------------------
# AC-4: POST /Startup/Complete
# --------------------------------------------------------------------------------------------


async def test_ac4_complete_needs_no_password_and_no_library_and_closes_the_window(
    app: FastAPI,
) -> None:
    assert (await first_user(app)).status_code == 200

    answered = await ask(app, LOOPBACK, "POST", "/Startup/Complete")

    assert answered.status_code == 204
    assert answered.content == b""
    assert await wizard_completed(app) is True
    assert json.loads(app.state.paths.state_file.read_text(encoding="utf-8"))[
        "startup_wizard_completed"
    ]
    assert (await first_user(app)).status_code == 401


async def test_ac4_a_second_complete_by_an_administrator_is_204_again(app: FastAPI) -> None:
    make_account(app, "Admin", administrator=True)
    assert (await ask(app, LOOPBACK, "POST", "/Startup/Complete")).status_code == 204
    token = await token_for(app, ELSEWHERE, "Admin")

    again = await ask(app, ELSEWHERE, "POST", "/Startup/Complete", token=token)

    assert again.status_code == 204
    assert await wizard_completed(app) is True


async def test_ac4_a_second_complete_with_no_token_is_401_with_an_empty_body(app: FastAPI) -> None:
    assert (await ask(app, LOOPBACK, "POST", "/Startup/Complete")).status_code == 204
    again = await ask(app, LOOPBACK, "POST", "/Startup/Complete")
    assert again.status_code == 401
    assert again.content == b""
    assert "content-type" not in again.headers


async def test_ac4_a_state_file_that_cannot_be_written_leaves_the_window_open(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The flag in memory moves only after the file has it (plan section 7)."""

    def refuse(*_args: object) -> None:
        raise ConfigurationError("the disk said no")

    monkeypatch.setattr("atrium.api.startup.save", refuse)
    transport = httpx.ASGITransport(app=app, client=(LOOPBACK, 51234), raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://atrium:8096") as opened:
        answered = await opened.post("/Startup/Complete")

    assert answered.status_code == 500
    assert app.state.server_state.startup_wizard_completed is False
    monkeypatch.undo()
    assert (await ask(app, LOOPBACK, "POST", "/Startup/Complete")).status_code == 204
