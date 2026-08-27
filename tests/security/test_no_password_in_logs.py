# SPDX-License-Identifier: GPL-3.0-or-later
"""A password must not reach a log record. At any level, from any logger, in any field.

**`DEBUG` is the point.** Nobody logs a password at `INFO`; it arrives at `DEBUG`, inside a
request trace, an exception message or the `repr` of an object somebody passed to `logger.debug`
without looking at what was in it.

So this captures **every** record from **every** logger, including the ones that do not propagate
to the root, and looks in every field a record carries: the message, the arguments, the formatted
output and the formatted traceback. Then it asserts the capture can actually fail, because a
guard that cannot fail is decoration (plan section 8.2).

**Two claims, two scopes, and the difference is stated rather than blurred.** The password must not
appear *at any level, from any logger* - that is a promise this project can keep, because a
password never leaves `users/passwords.py`. The stored **hash** and the **token** must not appear
under the logging an Atrium server actually ships with; asserting them under force-everything-to-
DEBUG would be promising that a debug-everything mode is safe, and nobody can keep that.

Both of the shipped-configuration tests failed when they were first written, and neither failure
was anything this project wrote:

* SQLAlchemy logs every statement **and its bound parameters** as soon as its logger is enabled for
  `INFO`, which `logging.basicConfig(level=INFO)` does. The bound parameters here are password
  hashes and token hashes.
* `?api_key=` puts a live credential in a **URL**, which is the field an access log exists to
  record.

`atrium.logs` is the answer to both, and this file is why it exists.
"""

from __future__ import annotations

import logging
import traceback
from collections.abc import Iterator

import httpx
import pytest
from fastapi import FastAPI

from atrium.compat.auth import ClientInfo
from atrium.compat.errors import AccountUnavailableError, InvalidCredentialsError
from atrium.compat.guids import new_id
from atrium.db.repositories import UserRepository
from atrium.domain.user import User

#: Distinctive enough that a substring search cannot miss it and cannot match by accident.
PASSWORD = "kestrel-anvil-42-QUARTZ-lantern"
CLIENT_HEADER = 'MediaBrowser Client="Atrium Test", Device="Bench", DeviceId="bench-1", Version="1"'


class Capture(logging.Handler):
    """Everything, from everywhere, in every field a record has."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    def everything(self) -> str:
        """One string to search. Cheaper to read than four assertions that mean the same thing."""
        parts: list[str] = []
        for record in self.records:
            parts.append(str(record.msg))
            parts.append(str(record.args))
            try:
                parts.append(record.getMessage())
                parts.append(self.format(record))
            except Exception as exc:  # a record that cannot even format is still evidence
                parts.append(repr(exc))
            if record.exc_info and record.exc_info[0] is not None:
                parts.append("".join(traceback.format_exception(*record.exc_info)))
        return "\n".join(parts)


@pytest.fixture
def shipped_logs() -> Iterator[Capture]:
    """Capture everything, under the logging configuration an Atrium server ships with.

    The weaker claim, deliberately: what a server writes down when somebody runs it, rather than
    what it would write down if every logger in the process were turned up to `DEBUG`.
    """
    from atrium import logs as log_setup

    handler = Capture()
    handler.setFormatter(logging.Formatter("%(name)s %(levelname)s %(message)s"))
    root = logging.getLogger()
    before = {name: logging.getLogger(name).level for name in log_setup.NOISY}
    before_root = root.level

    log_setup.configure(logging.DEBUG)
    handler.addFilter(log_setup.RedactCredentials())
    root.addHandler(handler)
    try:
        yield handler
    finally:
        root.removeHandler(handler)
        root.setLevel(before_root)
        for name, level in before.items():
            logging.getLogger(name).setLevel(level)
        root.filters = [f for f in root.filters if not isinstance(f, log_setup.RedactCredentials)]
        for existing in root.handlers:
            existing.filters = [
                f for f in existing.filters if not isinstance(f, log_setup.RedactCredentials)
            ]


@pytest.fixture
def logs() -> Iterator[Capture]:
    """Attach to the root **and** to every logger that does not propagate to it.

    `caplog` alone would miss a logger configured with `propagate = False`, which is exactly how a
    library that logs request details tends to be set up - so it is the one that would leak.
    """
    handler = Capture()
    handler.setFormatter(logging.Formatter("%(name)s %(levelname)s %(message)s"))

    root = logging.getLogger()
    touched: list[tuple[logging.Logger, int]] = [(root, root.level)]
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)

    for name in list(logging.Logger.manager.loggerDict):
        existing = logging.getLogger(name)
        touched.append((existing, existing.level))
        existing.setLevel(logging.DEBUG)
        if not existing.propagate:
            existing.addHandler(handler)

    previous_disable = logging.root.manager.disable
    logging.disable(logging.NOTSET)
    try:
        yield handler
    finally:
        logging.disable(previous_disable)
        for logger, level in touched:
            logger.setLevel(level)
            if handler in logger.handlers:
                logger.removeHandler(handler)


def make_user(app: FastAPI, name: str = "Joan", **overrides: object) -> User:
    fields: dict[str, object] = {
        "id": new_id(),
        "name": name,
        "password_hash": app.state.passwords.hash(PASSWORD),
    }
    fields.update(overrides)
    with app.state.sessions.begin() as opened:
        return UserRepository(opened).add(User(**fields))  # type: ignore[arg-type]


def phone() -> ClientInfo:
    return ClientInfo(client="Atrium Test", device="Bench", device_id="bench-1", version="1.0")


# --------------------------------------------------------------------------------------------
# The capture is a capture
# --------------------------------------------------------------------------------------------


def test_the_capture_sees_a_deliberate_leak(logs: Capture) -> None:
    """A guard that cannot fail is decoration. This is the failure it exists to catch."""
    logging.getLogger("atrium.test").debug("authenticating with %s", PASSWORD)
    assert PASSWORD in logs.everything()


def test_the_capture_sees_a_logger_that_does_not_propagate(logs: Capture) -> None:
    """The shape `caplog` alone would miss, and the one a request-tracing library tends to have."""
    quiet = logging.getLogger("atrium.test.quiet")
    quiet.propagate = False
    quiet.addHandler(logs)
    quiet.setLevel(logging.DEBUG)
    try:
        quiet.debug("the password was %s", PASSWORD)
        assert PASSWORD in logs.everything()
    finally:
        quiet.removeHandler(logs)
        quiet.propagate = True


def test_the_capture_sees_a_password_inside_a_traceback(logs: Capture) -> None:
    try:
        raise ValueError(f"could not parse {PASSWORD}")
    except ValueError:
        logging.getLogger("atrium.test").debug("failed", exc_info=True)
    assert PASSWORD in logs.everything()


# --------------------------------------------------------------------------------------------
# Authenticating, through the service
# --------------------------------------------------------------------------------------------


def test_a_successful_authentication_logs_no_password(app: FastAPI, logs: Capture) -> None:
    make_user(app)
    app.state.authenticator.authenticate("Joan", PASSWORD, phone())
    assert PASSWORD not in logs.everything()


def test_a_wrong_password_is_not_logged_either(app: FastAPI, logs: Capture) -> None:
    """The failure path is the tempting one: somebody adds the attempt to a log line to debug it."""
    make_user(app)
    with pytest.raises(InvalidCredentialsError):
        app.state.authenticator.authenticate("Joan", "the-wrong-" + PASSWORD, phone())
    assert PASSWORD not in logs.everything()
    assert "the-wrong-" not in logs.everything()


def test_an_unknown_username_logs_neither_name_nor_password(app: FastAPI, logs: Capture) -> None:
    with pytest.raises(InvalidCredentialsError):
        app.state.authenticator.authenticate("nobody-at-all", PASSWORD, phone())
    assert PASSWORD not in logs.everything()


def test_a_disabled_account_logs_no_password(app: FastAPI, logs: Capture) -> None:
    make_user(app, name="Gone", is_disabled=True)
    with pytest.raises(AccountUnavailableError):
        app.state.authenticator.authenticate("Gone", PASSWORD, phone())
    assert PASSWORD not in logs.everything()


def test_an_unreadable_record_logs_the_account_and_not_the_attempt(
    app: FastAPI, logs: Capture
) -> None:
    """This path *does* log - plan section 7 says name the user, because somebody has to reset a
    password rather than remember one. The username is the point; the attempt must not be."""
    make_user(app, name="Legacy", password_hash="$pbkdf2-sha512$iterations=210000$0011$aabb")
    with pytest.raises(InvalidCredentialsError):
        app.state.authenticator.authenticate("Legacy", PASSWORD, phone())

    written = logs.everything()
    assert "Legacy" in written, "the operator was not told which account needs a reset"
    assert PASSWORD not in written


def test_the_stored_hash_does_not_reach_a_log_either(app: FastAPI, shipped_logs: Capture) -> None:
    """A hash is not a password, and it is still not something to write down.

    Two ways it could: `User.password_hash` is excluded from the dataclass `repr`, so
    `logger.debug("%s", user)` cannot print it - and SQLAlchemy logs bound parameters once its
    logger reaches `INFO`, which is how it got into the log the first time this test ran.
    `atrium.logs` sets that logger to `WARNING`, deliberately, so an operator who wants SQL echoed
    turns it on rather than getting it with `basicConfig`.
    """
    user = make_user(app)
    logging.getLogger("atrium.test").debug("the user is %r", user)
    app.state.authenticator.authenticate("Joan", PASSWORD, phone())

    assert user.password_hash is not None
    assert user.password_hash not in shipped_logs.everything()


# --------------------------------------------------------------------------------------------
# Authenticating, over HTTP
# --------------------------------------------------------------------------------------------


async def test_the_password_does_not_reach_a_log_through_the_route(
    app: FastAPI, client: httpx.AsyncClient, logs: Capture
) -> None:
    make_user(app)
    answered = await client.post(
        "/Users/AuthenticateByName",
        json={"Username": "Joan", "Pw": PASSWORD},
        headers={"X-Emby-Authorization": CLIENT_HEADER},
    )
    assert answered.status_code == 200
    assert PASSWORD not in logs.everything()


async def test_a_refusal_does_not_echo_the_attempt_into_its_body(
    app: FastAPI, client: httpx.AsyncClient, logs: Capture
) -> None:
    """Nor into a log. A validation error that quoted the offending value would do both."""
    make_user(app)
    refused = await client.post(
        "/Users/AuthenticateByName",
        json={"Username": "Joan", "Pw": PASSWORD + "-wrong"},
        headers={"X-Emby-Authorization": CLIENT_HEADER},
    )
    assert refused.status_code == 401
    assert PASSWORD.encode("utf-8") not in refused.content
    assert PASSWORD not in logs.everything()


async def test_a_malformed_body_does_not_quote_what_was_sent(
    app: FastAPI, client: httpx.AsyncClient, logs: Capture
) -> None:
    """The framework's own validation errors quote the value they rejected, which is the one
    place a password reaches a response body without anybody deciding it should."""
    refused = await client.post(
        "/Users/AuthenticateByName",
        json={"Username": ["not", "a", "string"], "Pw": PASSWORD},
        headers={"X-Emby-Authorization": CLIENT_HEADER},
    )
    assert refused.status_code >= 400
    assert PASSWORD.encode("utf-8") not in refused.content
    assert PASSWORD not in logs.everything()


# --------------------------------------------------------------------------------------------
# The token, which travels in a URL
# --------------------------------------------------------------------------------------------


async def test_a_token_in_a_query_string_is_redacted(
    app: FastAPI, client: httpx.AsyncClient, shipped_logs: Capture
) -> None:
    """`?api_key=` puts a live credential in a **URL** - the field an access log exists to record.

    This failed when it was written, and what leaked it was the HTTP client library logging the
    request line. Anything in the chain does that: uvicorn's access log is the one that matters in
    production, and it is enabled by the same `basicConfig` call. The filter rewrites the value and
    leaves the log useful.
    """
    make_user(app)
    token = app.state.authenticator.authenticate("Joan", PASSWORD, phone()).token.secret

    served = await client.get(f"/Users/Me?api_key={token}")
    assert served.status_code == 200

    written = shipped_logs.everything()
    assert token not in written
    if "api_key" in written:
        assert "api_key=REDACTED" in written, "the parameter was logged without being redacted"


def test_the_redaction_leaves_the_rest_of_the_line_alone() -> None:
    """A log with the request removed is not a log. The path, method and status all survive."""
    from atrium.logs import RedactCredentials

    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '127.0.0.1 - "GET /Users/Me?api_key=%s&Fields=Path HTTP/1.1" 200',
        ("a1b2c3",),
        None,
    )
    RedactCredentials().filter(record)
    written = record.getMessage()
    assert "a1b2c3" not in written
    assert "api_key=REDACTED" in written
    assert "GET /Users/Me" in written
    assert "Fields=Path" in written
    assert written.endswith("200")


@pytest.mark.parametrize("spelling", ["api_key", "ApiKey", "APIKEY"])
def test_both_spellings_of_the_parameter_are_redacted(spelling: str) -> None:
    """They differ only in case, and a third would be a client's typo rather than a mechanism."""
    from atrium.logs import RedactCredentials

    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        f"GET /Users/Me?{spelling}=secret-value-here HTTP/1.1",
        (),
        None,
    )
    RedactCredentials().filter(record)
    assert "secret-value-here" not in record.getMessage()
