#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""What does a Jellyfin answer when an administrator makes, restricts and removes an account?

[015](../specs/015-user-administration/spec.md) opened on 2026-09-16 with fourteen questions and no
measurements. Four were decisions and all four were taken that day; **eight are readings, and two
are the plan's**. This probe takes the eight.

**Every one of them writes** - an account, a policy, a password, a playlist, a deletion - which is
why it refuses a server argument and measures only an instance it starts and destroys. 015 §7 says
the same thing the other way round: the operator's own server answers `12.0.0` since 2026-09-12, so
a reading taken there is not a reading of the pinned contract.

What it answers, by 015's numbering:

* **OQ-1** - the refusal envelopes. `POST /Users/New` declares `200`, `401`, `403` and `503` and
  **no refusal at all** `[spec: CreateUserByName]`, and `POST /Users/{userId}/Policy` answers a
  `404` its own document does not carry
  `[source: Jellyfin.Api/Controllers/UserController.cs:436-478 @ v10.11.11]`. This reads the
  status, the content type and the first bytes of each, against
  [behaviours §1.11](../docs/compatibility/behaviours.md)'s four shapes;
* **OQ-4** - whether a creation can fail *after* the account exists. The reference sets the
  password in a second step, on an account it has already committed
  `[source: UserController.cs:541-556 @ v10.11.11]`, so this asks what each refusal leaves behind;
* **OQ-5** - a policy body that omits properties: are the absent ones reset to their defaults, or
  kept? And what does a body that is not a whole document answer?
* **OQ-6** - what a disabling revokes, from a client's side: the token the account was holding, and
  the sign-in that would replace it;
* **OQ-8** - what `ResetPassword` leaves: whether the account then signs in with an empty password,
  with none, or not at all;
* **OQ-9** - the asymmetry `UpdateUserPassword` is written with: an administrator naming *itself*
  in `userId` must give its current password, and the same administrator omitting `userId` need
  not;
* **OQ-10** - what deleting an account does to the playlists it owns, private and public;
* **OQ-11** - whether the last administrator can be deleted, leaving a server nobody can
  administer. **This one is taken last and on purpose**: if the answer is yes, the run's own
  credentials stop working, and everything this probe created is already removed by then.

It also checks the four refusals 015 §3.3 states from the source - no such account, the last
administrator demoted, an administrator disabled, the last enabled account disabled - and reports a
contradiction if one does not hold. **The third of those may be unreachable**, and that is a
reading rather than a gap: an administrator cannot be disabled at all, so the only enabled account
can be reached only when it is not one.

**The library is `Movies` alone**, not the whole tree: this probe needs one item to put in a
playlist and nothing else from the fixture, and a scan of eighteen films is the cheapest way to
have one. Remote metadata providers are off, which is `_reference.library_options`'s measured
default.

Standard library only, on the 3.9 floor, and `--help` starts nothing.

Usage:
    python3 tools/probe_user_administration.py --allow-writes
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import json
import secrets
import sys
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
REPOSITORY = HERE.parent

#: The fixture tree, mounted read-only at `_reference.FIXTURE_MOUNT`.
TREE = REPOSITORY / "reference" / "fixture-tree"

#: The accounts this probe makes. Throwaway, removed by the register, and destroyed with the
#: instance either way. Numbered by what each one is for, so a reading names the account it was
#: taken on.
SEAT_POLICY = "atrium-probe-policy"
SEAT_DISABLE = "atrium-probe-disable"
SEAT_RESET = "atrium-probe-reset"
SEAT_CREDENTIAL = "atrium-probe-password"
SEAT_PLAYLISTS = "atrium-probe-playlists"
SECOND_ADMINISTRATOR = "atrium-probe-admin2"

#: The names a creation is refused under. None of them may leave an account behind (OQ-4).
REFUSED_NAMES: Tuple[Tuple[str, str], ...] = (
    ("empty", ""),
    ("whitespace", "   "),
    ("a slash", "bad/name"),
    ("a colon", "bad:name"),
    ("a leading space", " leading"),
    ("a trailing space", "trailing "),
)

DOCUMENT = "specs/015-user-administration/spec.md"
SECTION = "section 7, OQ-1, OQ-4, OQ-5, OQ-6 and OQ-8 to OQ-11"
EXPECTATION = (
    "015 sections 3.1 to 3.5, as amended at this gate on 2026-09-16: POST /Users/New answers 200 "
    "with the new account's document; a name that is blank or holds a refused character, and a "
    "name another account holds in any case, are refused and leave no account; GET /Users is "
    "ordered by name; POST /Users/{userId}/Policy answers 404 for an account that does not exist "
    "and 403 for demoting the only administrator and for disabling one; a disabling revokes that "
    "account's tokens; a reset password leaves an account that signs in with none; an "
    "administrator changes another account's password without giving the current one, and a wrong "
    "current password is 403; the userId asymmetry is real; deleting an account revokes its "
    "tokens; and the last administrator cannot delete itself - the refusal arriving after the "
    "same request has already revoked its tokens"
)


def load(name: str) -> Any:
    """A sibling of this script, loaded by path and on first use, never at import."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, HERE / (name + ".py"))
    if spec is None or spec.loader is None:  # pragma: no cover - the files are beside this one
        raise SystemExit(f"tools/{name}.py could not be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def shape(answered: Tuple[int, Dict[str, str], bytes]) -> str:
    """A refusal as it arrived: status, content type and the body's first bytes, verbatim."""
    status, headers, payload = answered
    kind = headers.get("Content-Type") or headers.get("content-type") or "no Content-Type"
    return f"{status} {kind} {payload[:200]!r}"


def status_of(answered: Tuple[int, Dict[str, str], bytes]) -> int:
    return answered[0]


def body_of(answered: Tuple[int, Dict[str, str], bytes]) -> Any:
    """The body parsed as sent, so a key that arrived `null` is still a key."""
    try:
        return json.loads(answered[2].decode("utf-8")) if answered[2] else None
    except ValueError:
        return None


def names_on(server: Any) -> List[str]:
    rows = server.get("/Users")
    return [str(row.get("Name")) for row in rows] if isinstance(rows, list) else []


def fixture_entry_point() -> Any:
    """`tests/fixtures/reference_tree.py`, imported the way the other probes import it."""
    root = str(REPOSITORY)
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        from tests.fixtures import reference_tree
    except ImportError as failure:  # pragma: no cover - a checkout missing its own tests
        raise load("_probe").ProbeError(
            f"could not import tests.fixtures.reference_tree from {REPOSITORY}: {failure}"
        ) from failure
    return reference_tree


class Reading:
    """One configured instance, and the five operations walked on it as its administrator."""

    def __init__(self) -> None:
        self.instance: Optional[Any] = None
        self.administrator: Optional[Any] = None

    @contextlib.contextmanager
    def connect(self, args: argparse.Namespace) -> Iterator[Any]:
        probe = load("_probe")
        reference = load("_reference")
        if getattr(args, "server", None):
            raise probe.ProbeError(
                "this probe refuses a server argument. Every question it asks writes - an "
                "account, a policy, a password, a playlist, a deletion, and finally the "
                "administrator itself - so it measures only an instance it starts and destroys. "
                "The last reading it takes may leave the server unadministrable, which is the "
                "answer to OQ-11 and not a state to leave on a server somebody owns"
            )
        tree = fixture_entry_point()
        if not tree.is_complete(TREE):
            tree.build(TREE)
        try:
            spec = reference.InstanceSpec(
                fixture_root=TREE,
                libraries=(
                    reference.Library(name="Films", collection_type="movies", subpath="Movies"),
                ),
            )
            with reference.ReferenceInstance(spec) as instance:
                self.instance = instance
                if instance.administrator is None:  # pragma: no cover - configure=True made one
                    raise probe.ProbeError("the instance stood up without an administrator")
                server = probe.Server(instance.url)
                server.connect(
                    instance.administrator.username, instance.administrator.password, None
                )
                self.administrator = instance.administrator
                yield server
        except reference.InstanceError as failure:
            raise probe.ProbeError(str(failure)) from failure

    # -- the walk ----------------------------------------------------------------------------

    def report(self, server: Any, _args: argparse.Namespace) -> Any:
        module = load("_probe")
        probe = module.Probe(
            script="probe_user_administration.py",
            question=(
                "What does a Jellyfin answer when an administrator makes, restricts and removes "
                "an account?"
            ),
            document=DOCUMENT,
            section=SECTION,
            expectation=EXPECTATION,
        )
        probe.observe("instance", self.instance.image if self.instance else "unknown")
        claims: Dict[str, bool] = {}
        made: List[str] = []

        def seat(name: str, password: str) -> Tuple[int, Any]:
            """Create an account and hand back what the route answered, whole."""
            answered = server.post_raw("/Users/New", body={"Name": name, "Password": password})
            if status_of(answered) == 200:
                made.append(str((body_of(answered) or {}).get("Id")))
            return status_of(answered), body_of(answered)

        def signs_in(name: str, password: Optional[str], device: str = "") -> Tuple[int, Any]:
            """A sign-in from a device of its own, so no token of this run is revoked.

            `device` names one explicitly for the case the first run of this probe got wrong:
            signing in **as the administrator** to check whether its account still works derives
            the same device the run itself signed in from, and the reference binds a token to a
            device - so the check revoked the token the teardown needed, and the cleanup reported
            a `401` on an account this probe had made.
            """
            other = module.Server(server.base, timeout=server.timeout)
            other.device_id = device or module.device_for(name)
            answered = other._request(
                "POST",
                "/Users/AuthenticateByName",
                body={"Username": name, "Pw": password if password is not None else ""},
                extra_headers={"Authorization": other.authorization()},
                raw=True,
            )
            return status_of(answered), body_of(answered)

        self._creations(server, probe, claims, seat)
        self._policy_body(server, probe, claims, seat)
        self._guards(server, probe, claims, seat)
        self._disabling(server, probe, claims, seat, signs_in, module)
        self._passwords(server, probe, claims, seat, signs_in, module)
        self._playlists(server, probe, claims, seat, module)
        self._last_administrator(server, probe, claims, made, signs_in)

        failed = sorted(name for name, held in claims.items() if not held)
        probe.conclude(
            "every claim 015 makes from the source and the pinned document held on the instance - "
            "the refusals and what they leave, the policy body's replacement semantics, the "
            "guards, the revocations and the deletion's reach; the readings above answer OQ-1, "
            "OQ-4, OQ-5, OQ-6 and OQ-8 to OQ-11"
            if not failed
            else f"{len(failed)} claim(s) 015 makes did not hold: {failed}",
            matches_documentation=not failed,
        )
        probe.note(
            "Every account and every playlist this run made is removed before the last reading, "
            "and the instance is destroyed with everything it wrote either way. The last reading "
            "deletes the administrator this run signed in as, so a teardown after it reports "
            "REVOKED rather than a leak - which is the register's own class for a token that "
            "stopped working, and not a probe that forgot to clean up."
        )
        return probe

    # -- OQ-1 and OQ-4: what a creation answers, and what a refusal leaves --------------------

    def _creations(self, server: Any, probe: Any, claims: Dict[str, bool], seat: Any) -> None:
        before = names_on(server)
        probe.observe("accounts on a configured instance, before this probe", before)

        password = secrets.token_hex(16)
        status, document = seat(SEAT_POLICY, password)
        probe.observe("POST /Users/New, valid", status)
        claims["a creation answers 200"] = status == 200
        if isinstance(document, dict):
            probe.observe("  the new account's document, key set", sorted(document))
            policy = document.get("Policy")
            configuration = document.get("Configuration")
            flags = (
                [
                    policy.get(key)
                    for key in ("IsHidden", "IsDisabled", "IsAdministrator", "EnableAllFolders")
                ]
                if isinstance(policy, dict)
                else "-"
            )
            probe.observe(
                "OQ-5: the default policy, property count and IsHidden/IsDisabled/"
                "IsAdministrator/EnableAllFolders",
                f"{len(policy) if isinstance(policy, dict) else 'absent'} properties; {flags}",
            )
            probe.observe(
                "  the default configuration, property count",
                len(configuration) if isinstance(configuration, dict) else "absent",
            )
            if isinstance(policy, dict):
                probe.observe("  the default policy, whole", json.dumps(policy, sort_keys=True))
            if isinstance(configuration, dict):
                probe.observe(
                    "  the default configuration, whole", json.dumps(configuration, sort_keys=True)
                )

        for label, name in REFUSED_NAMES:
            answered = server.post_raw("/Users/New", body={"Name": name, "Password": password})
            probe.observe(f"OQ-1: POST /Users/New with a name that is {label}", shape(answered))
            after = names_on(server)
            probe.observe("  accounts after it", len(after))
            claims[f"a name that is {label} is refused"] = status_of(answered) >= 400
            claims[f"a name that is {label} leaves no account"] = len(after) == len(before) + 1

        for label, name in (("exactly", SEAT_POLICY), ("in another case", SEAT_POLICY.upper())):
            answered = server.post_raw("/Users/New", body={"Name": name, "Password": password})
            probe.observe(f"OQ-1: a name another account holds {label}", shape(answered))
            after = names_on(server)
            claims[f"a duplicate {label} is refused"] = status_of(answered) >= 400
            claims[f"a duplicate {label} leaves no account"] = len(after) == len(before) + 1

        no_name = server.post_raw("/Users/New", body={"Password": password})
        probe.observe("OQ-1: a body with no Name", shape(no_name))
        no_body = server.post_raw("/Users/New")
        probe.observe("OQ-1: no body at all", shape(no_body))
        not_an_object = server.post_raw("/Users/New", raw_body=b"[]")
        probe.observe("OQ-1: a body that is not an object", shape(not_an_object))

        null_password = server.post_raw(
            "/Users/New", body={"Name": SEAT_CREDENTIAL + "-null", "Password": None}
        )
        probe.observe("OQ-4: a creation with a null password", shape(null_password))
        if status_of(null_password) == 200:
            identifier = str((body_of(null_password) or {}).get("Id"))
            document = server.get("/Users/" + identifier)
            probe.observe(
                "  HasPassword / HasConfiguredPassword on it",
                f"{document.get('HasPassword')} / {document.get('HasConfiguredPassword')}",
            )
            probe.observe(
                "OQ-4: no refusal after the account exists was reachable from here",
                "the password step takes any string the body carries, and a null one is skipped",
            )

        filters = server.get_raw("/Users", isHidden="banana")
        probe.observe("OQ-1: GET /Users with a filter that is not a boolean", shape(filters))
        ordered = names_on(server)
        probe.observe("GET /Users, in the order it answered", ordered)
        claims["GET /Users is ordered by name"] = ordered == sorted(
            ordered, key=lambda text: text.upper()
        )

    # -- OQ-5: what a policy body that is not whole does --------------------------------------

    def _policy_body(self, server: Any, probe: Any, claims: Dict[str, bool], seat: Any) -> None:
        password = secrets.token_hex(16)
        status, document = seat(SEAT_DISABLE + "-policy", password)
        if status != 200 or not isinstance(document, dict):
            probe.observe("OQ-5: skipped", f"the account could not be created ({status})")
            return
        identifier = str(document["Id"])
        whole = server.get("/Users/" + identifier)["Policy"]

        answered = server.post_raw(
            "/Users/" + identifier + "/Policy", body={"IsAdministrator": False}
        )
        probe.observe("OQ-5: a policy body naming one property", shape(answered))
        after = server.get("/Users/" + identifier)["Policy"]
        changed = sorted(key for key in set(whole) | set(after) if whole.get(key) != after.get(key))
        probe.observe("  properties whose value changed", changed)
        probe.observe(
            "  EnableAllFolders / EnableMediaPlayback before and after",
            f"{whole.get('EnableAllFolders')}->{after.get('EnableAllFolders')} / "
            f"{whole.get('EnableMediaPlayback')}->{after.get('EnableMediaPlayback')}",
        )
        claims["a partial policy body is a replacement"] = bool(changed) or whole == after

        # The first run answered the question above with a refusal rather than a semantics, so
        # the question moves: **which properties are required**, and for one that is not, does
        # leaving it out keep the stored value or take the type's default?
        #
        # **Each property is moved off its default first, and the second run of this probe did
        # not do that.** Omitting `EnableAllFolders` from a policy where it is already `true` -
        # its own default - cannot tell "kept" from "reset": both answers are `true`. So each
        # property below is set to something the default is not, and only then left out.
        moved = {
            "EnableAllFolders": False,
            "EnableMediaPlayback": False,
            "LoginAttemptsBeforeLockout": 7,
            "MaxActiveSessions": 3,
            "EnableContentDownloading": False,
        }
        required_candidates = (
            ("PasswordResetProviderId", None),
            ("AuthenticationProviderId", None),
        )
        for omitted, unusual in (*moved.items(), *required_candidates):
            current = dict(server.get("/Users/" + identifier)["Policy"])
            if unusual is not None:
                current[omitted] = unusual
                set_it = server.post_raw("/Users/" + identifier + "/Policy", body=current)
                stored = server.get("/Users/" + identifier)["Policy"].get(omitted)
                if status_of(set_it) not in (200, 204) or stored != unusual:
                    probe.observe(
                        f"OQ-5: {omitted} could not be moved off its default",
                        f"{status_of(set_it)}, it is {stored!r}",
                    )
                    continue
                current = dict(server.get("/Users/" + identifier)["Policy"])
            was = current.get(omitted)
            body = {key: value for key, value in current.items() if key != omitted}
            answered = server.post_raw("/Users/" + identifier + "/Policy", body=body)
            state = server.get("/Users/" + identifier)["Policy"]
            probe.observe(
                f"OQ-5: a whole policy with {omitted} left out",
                f"{status_of(answered)} -> it is now {state.get(omitted)!r} (it was {was!r}, "
                f"and the default is {whole.get(omitted)!r})",
            )

        empty = server.post_raw("/Users/" + identifier + "/Policy", body={})
        probe.observe("OQ-5: an empty policy body", shape(empty))
        not_an_object = server.post_raw("/Users/" + identifier + "/Policy", raw_body=b"[]")
        probe.observe("OQ-5: a policy body that is not an object", shape(not_an_object))
        no_body = server.post_raw("/Users/" + identifier + "/Policy")
        probe.observe("OQ-5: no policy body at all", shape(no_body))

        unknown = dict(server.get("/Users/" + identifier)["Policy"])
        unknown["AtriumMadeThisUp"] = True
        answered = server.post_raw("/Users/" + identifier + "/Policy", body=unknown)
        probe.observe(
            "OQ-5: a policy carrying a property the reference has never heard of", shape(answered)
        )
        back = server.get("/Users/" + identifier)["Policy"]
        probe.observe("  does it come back?", "AtriumMadeThisUp" in back)

    # -- OQ-1 and §3.3: the four refusals of a policy update ----------------------------------

    def _guards(self, server: Any, probe: Any, claims: Dict[str, bool], seat: Any) -> None:
        administrator = str(server.user_id)
        mine = server.get("/Users/" + administrator)["Policy"]

        # **A whole policy, and the first run of this probe got that wrong.** A body naming one
        # property is refused by model validation before the route runs, so the `404` the source
        # shows for an account that does not exist sits behind a `400` and cannot be read with
        # one. What is measured here is the route's own refusal, which needs a body the route
        # actually reaches.
        # **A random identifier, and the second run of this probe got that wrong too.** The
        # all-zeros identifier is not *an account that does not exist*: it is the one identifier
        # the reference refuses before it looks anything up, which is the shape 009 met on
        # `POST /Playlists`. Both are read, because the difference between them is the reading.
        nobody = secrets.token_hex(16)
        absent = server.post_raw("/Users/" + nobody + "/Policy", body=dict(mine))
        probe.observe("OQ-1: a whole policy for an account that does not exist", shape(absent))
        claims["an absent account is 404"] = status_of(absent) == 404

        zeros = server.post_raw("/Users/00000000000000000000000000000000/Policy", body=dict(mine))
        probe.observe("OQ-1: the same, for the all-zeros identifier", shape(zeros))

        partial_absent = server.post_raw(
            "/Users/" + nobody + "/Policy", body={"IsAdministrator": False}
        )
        probe.observe(
            "OQ-1: and a partial body for that same absent account", shape(partial_absent)
        )

        malformed = server.post_raw("/Users/not-an-identifier/Policy", body=dict(mine))
        probe.observe("OQ-1: a whole policy for an identifier that is not one", shape(malformed))
        probe.observe(
            "administrators on this instance",
            sum(
                1
                for row in server.get("/Users")
                if isinstance(row, dict)
                and isinstance(row.get("Policy"), dict)
                and row["Policy"].get("IsAdministrator")
            ),
        )

        demoted = dict(mine)
        demoted["IsAdministrator"] = False
        answered = server.post_raw("/Users/" + administrator + "/Policy", body=demoted)
        probe.observe("§3.3: demoting the only administrator", shape(answered))
        claims["the only administrator cannot be demoted"] = status_of(answered) == 403

        disabled = dict(mine)
        disabled["IsDisabled"] = True
        answered = server.post_raw("/Users/" + administrator + "/Policy", body=disabled)
        probe.observe("§3.3: disabling an administrator", shape(answered))
        claims["an administrator cannot be disabled"] = status_of(answered) == 403

        still = server.get("/Users/" + administrator)["Policy"]
        probe.observe(
            "  the administrator's policy after both refusals",
            f"IsAdministrator={still.get('IsAdministrator')} IsDisabled={still.get('IsDisabled')}",
        )
        claims["a refused policy update changes nothing"] = (
            still.get("IsAdministrator") is True and still.get("IsDisabled") is not True
        )

        probe.note(
            "The third guard - `There must be at least one enabled user in the system` - was not "
            "reached, and the reason is the second one. It fires only when the account being "
            "disabled is the last enabled one, and on this instance that account is an "
            "administrator, which the guard above refuses first. Reaching it would need a server "
            "whose only enabled account is not an administrator, which the guard above makes "
            "unreachable from a running start."
        )

    # -- OQ-6: what a disabling revokes -------------------------------------------------------

    def _disabling(
        self,
        server: Any,
        probe: Any,
        claims: Dict[str, bool],
        seat: Any,
        signs_in: Any,
        module: Any,
    ) -> None:
        password = secrets.token_hex(16)
        status, document = seat(SEAT_DISABLE, password)
        if status != 200 or not isinstance(document, dict):
            probe.observe("OQ-6: skipped", f"the account could not be created ({status})")
            return
        identifier = str(document["Id"])

        held = module.Server(server.base, timeout=server.timeout)
        held.connect(SEAT_DISABLE, password, None)
        probe.observe("OQ-6: the seat holds a token", held.get_raw("/Users/Me")[0])

        policy = dict(server.get("/Users/" + identifier)["Policy"])
        policy["IsDisabled"] = True
        answered = server.post_raw("/Users/" + identifier + "/Policy", body=policy)
        probe.observe("OQ-6: disabling a non-administrator", shape(answered))
        claims["a non-administrator can be disabled"] = status_of(answered) in (200, 204)

        probe.observe(
            "OQ-6: the token it was holding, afterwards", shape(held.get_raw("/Users/Me"))
        )
        again = signs_in(SEAT_DISABLE, password)
        probe.observe("OQ-6: signing in again, afterwards", f"{again[0]} {str(again[1])[:160]}")
        claims["a disabled account cannot sign in"] = again[0] >= 400

        listed = server.get_raw("/Users", isDisabled="true")
        rows = body_of(listed) or []
        probe.observe(
            "OQ-6: GET /Users?isDisabled=true",
            [str(row.get("Name")) for row in rows] if isinstance(rows, list) else shape(listed),
        )
        public = server.get_raw("/Users/Public")
        rows = body_of(public) or []
        probe.observe(
            "  and /Users/Public",
            [str(row.get("Name")) for row in rows] if isinstance(rows, list) else shape(public),
        )

    # -- OQ-8 and OQ-9: the three paths through one password operation ------------------------

    def _passwords(
        self,
        server: Any,
        probe: Any,
        claims: Dict[str, bool],
        seat: Any,
        signs_in: Any,
        module: Any,
    ) -> None:
        original = secrets.token_hex(16)
        replacement = secrets.token_hex(16)

        status, document = seat(SEAT_RESET, original)
        if status == 200 and isinstance(document, dict):
            identifier = str(document["Id"])
            answered = server.post_raw(
                "/Users/Password", body={"ResetPassword": True}, userId=identifier
            )
            probe.observe("OQ-8: ResetPassword on another account", shape(answered))
            after = server.get("/Users/" + identifier)
            probe.observe(
                "  HasPassword / HasConfiguredPassword afterwards",
                f"{after.get('HasPassword')} / {after.get('HasConfiguredPassword')}",
            )
            with_none = signs_in(SEAT_RESET, None)
            with_old = signs_in(SEAT_RESET, original)
            probe.observe("OQ-8: signing in with no password", with_none[0])
            probe.observe("OQ-8: signing in with the old password", with_old[0])
            claims["a reset password leaves an account that signs in with none"] = (
                with_none[0] == 200
            )

        status, document = seat(SEAT_CREDENTIAL, original)
        if status == 200 and isinstance(document, dict):
            identifier = str(document["Id"])
            answered = server.post_raw(
                "/Users/Password", body={"NewPw": replacement}, userId=identifier
            )
            probe.observe(
                "OQ-9: an administrator changes another account's password, no CurrentPw",
                shape(answered),
            )
            claims["an administrator needs no current password for another account"] = status_of(
                answered
            ) in (200, 204)
            probe.observe("  the old password afterwards", signs_in(SEAT_CREDENTIAL, original)[0])
            probe.observe(
                "  the new password afterwards", signs_in(SEAT_CREDENTIAL, replacement)[0]
            )

            held = module.Server(server.base, timeout=server.timeout)
            held.connect(SEAT_CREDENTIAL, replacement, None)
            wrong = held.post_raw(
                "/Users/Password", body={"CurrentPw": "not-it", "NewPw": secrets.token_hex(8)}
            )
            probe.observe("OQ-9: the account changes its own with a wrong current", shape(wrong))
            claims["a wrong current password is 403"] = status_of(wrong) == 403

            others = held.post_raw(
                "/Users/Password",
                body={"NewPw": secrets.token_hex(8)},
                userId=str(server.user_id),
            )
            probe.observe("OQ-9: a non-administrator changes an administrator's", shape(others))
            claims["a non-administrator may not change another's password"] = (
                status_of(others) == 403
            )

        second = secrets.token_hex(16)
        status, document = seat(SECOND_ADMINISTRATOR, second)
        if status == 200 and isinstance(document, dict):
            identifier = str(document["Id"])
            policy = dict(server.get("/Users/" + identifier)["Policy"])
            policy["IsAdministrator"] = True
            elevated = server.post_raw("/Users/" + identifier + "/Policy", body=policy)
            probe.observe("OQ-9: a second administrator, made by policy", status_of(elevated))
            if status_of(elevated) in (200, 204):
                admin2 = module.Server(server.base, timeout=server.timeout)
                admin2.connect(SECOND_ADMINISTRATOR, second, None)
                named = admin2.post_raw(
                    "/Users/Password", body={"NewPw": secrets.token_hex(8)}, userId=identifier
                )
                probe.observe(
                    "OQ-9: an administrator naming ITSELF in userId, no CurrentPw", shape(named)
                )
                omitted = admin2.post_raw("/Users/Password", body={"NewPw": second})
                probe.observe(
                    "OQ-9: the same administrator OMITTING userId, no CurrentPw", shape(omitted)
                )
                claims["the userId asymmetry is real"] = status_of(named) != status_of(omitted)

    # -- OQ-10: what a deletion takes with it -------------------------------------------------

    def _playlists(
        self, server: Any, probe: Any, claims: Dict[str, bool], seat: Any, module: Any
    ) -> None:
        password = secrets.token_hex(16)
        status, document = seat(SEAT_PLAYLISTS, password)
        if status != 200 or not isinstance(document, dict):
            probe.observe("OQ-10: skipped", f"the account could not be created ({status})")
            return
        identifier = str(document["Id"])

        films = server.get(
            "/Items", userId=server.user_id, includeItemTypes="Movie", limit=1, recursive="true"
        )
        rows = films.get("Items") if isinstance(films, dict) else None
        if not rows:
            probe.observe("OQ-10: skipped", "the instance's library holds no film to put in one")
            return
        film = str(rows[0]["Id"])

        owner = module.Server(server.base, timeout=server.timeout)
        owner.connect(SEAT_PLAYLISTS, password, None)
        private = owner.post(
            "/Playlists",
            body={
                "Name": "atrium-probe-private",
                "Ids": [film],
                "UserId": identifier,
                "IsPublic": False,
            },
        )
        public = owner.post(
            "/Playlists",
            body={
                "Name": "atrium-probe-public",
                "Ids": [film],
                "UserId": identifier,
                "IsPublic": True,
            },
        )
        private_id = str(private["Id"])
        public_id = str(public["Id"])
        probe.observe("OQ-10: the seat owns two playlists", f"{private_id} {public_id}")

        removed = server.delete_raw("/Users/" + identifier)
        probe.observe("OQ-10: DELETE /Users/{id} on the owner", shape(removed))
        claims["a deletion answers 204"] = status_of(removed) == 204
        # Deleted with their owner or not, the register must not try them again: what it would
        # report is this reading's answer rather than a leak.
        module.OWNED.disown(owner, "/Items/" + private_id)
        module.OWNED.disown(owner, "/Items/" + public_id)
        module.OWNED.disown(server, "/Users/" + identifier)

        for label, playlist in (("private", private_id), ("public", public_id)):
            answered = server.get_raw("/Items/" + playlist, userId=server.user_id)
            probe.observe(
                f"OQ-10: the {label} playlist, read by the administrator", shape(answered)
            )

        again = server.delete_raw("/Users/" + identifier)
        probe.observe("OQ-10: deleting the same account twice", shape(again))
        claims["a second deletion is 404"] = status_of(again) == 404
        probe.observe("OQ-10: the seat's token afterwards", shape(owner.get_raw("/Users/Me")))

    # -- OQ-11: the last administrator, and the end of the run --------------------------------

    def _last_administrator(
        self,
        server: Any,
        probe: Any,
        claims: Dict[str, bool],
        made: List[str],
        signs_in: Any,
    ) -> None:
        module = load("_probe")
        for identifier in made:
            if not identifier or identifier == "None":
                continue
            with contextlib.suppress(Exception):
                server.delete("/Users/" + identifier)
            module.OWNED.disown(server, "/Users/" + identifier)
        left = names_on(server)
        probe.observe("accounts left before the last reading", left)

        administrator = str(server.user_id)
        answered = server.delete_raw("/Users/" + administrator)
        probe.observe("OQ-11: an administrator deletes its own, and only, account", shape(answered))
        # **The claim asserts the measurement, not the source.** 015 said from `DeleteUser` that
        # nothing here checks an administrator is left, and the server refuses anyway: the guard is
        # below the controller. Amended at this gate, and this is what holds it.
        claims["the last administrator cannot delete itself"] = status_of(answered) == 400

        # **What the refusal already did before refusing.** The controller revokes every token the
        # account holds and removes its playlists *before* the manager's guard raises
        # `[source: Jellyfin.Api/Controllers/UserController.cs:155-167 @ v10.11.11]`, so a refused
        # deletion is not a no-op. The first two runs of this probe reported it as a cleanup
        # failure - a `401` on an account it had made - before it was read here.
        own_token = server.get_raw("/Users/Me")
        probe.observe("OQ-11: the token this run was holding, after the refusal", shape(own_token))
        claims["a refused deletion has already revoked the tokens"] = status_of(own_token) == 401

        public = server.get_raw("/Users/Public")
        probe.observe("OQ-11: /Users/Public afterwards", shape(public))
        name = self.administrator.username if self.administrator else ""
        password = self.administrator.password if self.administrator else ""
        probe.observe(
            "OQ-11: signing in as it afterwards",
            signs_in(name, password, device=module.device_for(name + "-oq11-check"))[0],
        )
        probe.note(
            "If the reading above is a 204, the reference lets the last administrator delete "
            "itself and leaves a server nobody can administer and - since GET /Startup/User is "
            "closed once the wizard has completed - nobody can recover. That is what 015 §3.5 "
            "asks about, and it is measured last because every answer after it is taken on a "
            "server this run can no longer administer."
        )


def main() -> int:
    reading = Reading()
    return int(
        load("_probe").main(
            reading.report,
            description=(
                "Measure what a Jellyfin answers when an administrator makes, restricts and "
                "removes an account (015 OQ-1, OQ-4, OQ-5, OQ-6 and OQ-8 to OQ-11). Starts a "
                "single-use instance of the pinned version, walks the five operations as its "
                "administrator, and destroys the instance - including on failure. It never "
                "measures a server somebody owns."
            ),
            needs_writes=True,
            with_args=True,
            connect_with=reading.connect,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
