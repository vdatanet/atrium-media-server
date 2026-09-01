#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Who may read whom through GET /Users/{userId}, and what comes back when nobody may?

002 section 3.7 says the route answers 403 when the token belongs to a different, non-administrator
user. That sentence carried no provenance until 009 T2 measured one cell of it - a *restricted*
non-administrator naming an *administrator* - and found a 200 with the administrator's whole object,
Configuration and Policy included. One cell is not the route: the claim being replaced covers every
pair of caller and subject, plus the two identifiers that address nobody.

So this probe asks the whole matrix, in one run against one server:

  * an ordinary non-administrator naming another non-administrator
  * a user naming themselves
  * a restricted non-administrator naming an administrator - 009 T2's cell, reproduced
  * an administrator naming anybody
  * a userId that is well formed and belongs to nobody
  * a userId that is not an identifier at all
  * no credential whatsoever

Each cell prints its whole observable shape - status, content type, body length, first bytes - for
the reason behaviours section 1.11 gives: a 403 is two shapes on this reference, and a slice of the
body cannot tell an empty body from a body-less refusal. The disclosure cells print the property
names that came back beside the ones the subject sees of itself, because "answered 200" and
"answered 200 with Policy in it" are different findings and only the second one is a disclosure.

Writes: creates two throwaway non-administrator users, restricts one of them to a single library,
and deletes both afterwards, including on failure. It touches no account the operator owns - the
administrator cells read the .env account and never write to it.

Usage:
    python3 tools/probe_user_read.py http://your-jellyfin:8096 -u username --allow-writes
"""

from __future__ import annotations

import json
import secrets

from _probe import Probe, ProbeError, Server, main

READER = "atrium-probe-user-reader"
SUBJECT = "atrium-probe-user-subject"

#: Well formed, 32 hex, and belongs to nobody. Random rather than all-zeroes: an empty identifier
#: is a value the reference's own binder may treat specially, which would measure a different
#: question than "an identifier nobody has".
NOBODY = secrets.token_hex(16)
MALFORMED = "not-an-identifier"


def movies_view(server: Server) -> dict:
    for view in server.get("/UserViews", userId=server.user_id).get("Items", []):
        if view.get("CollectionType") == "movies":
            return view
    raise ProbeError("no movies library to restrict the throwaway reader to")


def shape(status: int, headers: dict, payload: bytes) -> str:
    """A refusal's whole observable shape, and an answer's size.

    The content type is the cell that decides which of the two 403 shapes a refusal is
    (behaviours section 1.11), and it is invisible in the body.
    """
    content_type = next(
        (value for key, value in headers.items() if key.lower() == "content-type"), None
    )
    return f"{status}  {content_type!r}  {len(payload)} bytes  {payload[:48]!r}"


def body_of(payload: bytes) -> dict:
    try:
        parsed = json.loads(payload)
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def run(server: Server) -> Probe:
    probe = Probe(
        script="probe_user_read.py",
        question="who may read whom through GET /Users/{userId}, and with what body?",
        document="specs/002-authentication-users-and-sessions/spec.md",
        section="section 3.7, AC-7 and the section 6 matrix",
        expectation=(
            "GET /Users/{userId} answers 403 when the token belongs to a different, "
            "non-administrator user"
        ),
    )

    existing = {user["Name"] for user in server.get("/Users")}
    for name in (READER, SUBJECT):
        if name in existing:
            raise ProbeError(
                f"a user called {name} already exists - an earlier run did not clean up. "
                "Remove it before measuring, so this probe cannot change a real account"
            )

    movies = movies_view(server)
    made: list[str] = []
    try:
        reader_password = secrets.token_hex(12)
        subject_password = secrets.token_hex(12)
        reader_id = server.post("/Users/New", body={"Name": READER, "Password": reader_password})[
            "Id"
        ]
        made.append(reader_id)
        subject_id = server.post(
            "/Users/New", body={"Name": SUBJECT, "Password": subject_password}
        )["Id"]
        made.append(subject_id)

        policy = server.get(f"/Users/{reader_id}")["Policy"]
        policy.update({"EnableAllFolders": False, "EnabledFolders": [movies["Id"]]})
        status, _, body = server.post_raw(f"/Users/{reader_id}/Policy", body=policy)
        if status not in (200, 204):
            raise ProbeError(f"could not restrict the throwaway reader: {status} {body[:120]!r}")

        reader = Server(server.base, timeout=server.timeout)
        reader.connect(READER, reader_password, None)
        anonymous = Server(server.base, timeout=server.timeout)
        anonymous.version = server.version

        probe.observe(
            "the two throwaway users",
            f"{READER} (non-administrator, restricted to {movies['Name']!r}) and "
            f"{SUBJECT} (non-administrator, unrestricted)",
        )
        probe.observe("the .env account", f"administrator, id {server.user_id}")
        probe.observe("", "")

        # -- the matrix ------------------------------------------------------------------------
        cells = [
            ("a non-administrator names another non-administrator", reader, subject_id),
            ("a non-administrator names themselves", reader, reader_id),
            ("a non-administrator names an ADMINISTRATOR  (009 T2's cell)", reader, server.user_id),
            ("an administrator names a non-administrator", server, reader_id),
            ("an administrator names themselves", server, server.user_id),
            ("a non-administrator names NOBODY  (32 hex, unused)", reader, NOBODY),
            ("an administrator names NOBODY", server, NOBODY),
            (f"a non-administrator sends {MALFORMED!r}", reader, MALFORMED),
            (f"an administrator sends {MALFORMED!r}", server, MALFORMED),
        ]
        answers: dict[str, tuple[int, dict, bytes]] = {}
        for label, caller, target in cells:
            answered = caller.get_raw(f"/Users/{target}")
            answers[label] = answered
            probe.observe(label, shape(*answered))

        no_token = anonymous.get_raw(f"/Users/{subject_id}")
        probe.observe("no credential at all", shape(*no_token))
        probe.observe(" ", " ")

        # -- the two refusals in full ----------------------------------------------------------
        # A 48-byte slice cannot show which key a validation 400 is filed under, and behaviours
        # section 1.11 says that key is the parameter's *declared* spelling rather than the
        # client's - so the whole body is printed for the two cells that carry one.
        probe.observe(
            "FULL BODY  an identifier nobody has",
            answers["an administrator names NOBODY"][2].decode("utf-8", "replace"),
        )
        probe.observe(
            f"FULL BODY  {MALFORMED!r}",
            answers[f"an administrator sends {MALFORMED!r}"][2].decode("utf-8", "replace"),
        )
        probe.observe("  ", "  ")

        # -- is a 200 a disclosure? ---------------------------------------------------------
        # "Answered 200" and "answered 200 with the subject's Policy in it" are different
        # findings, and only the second is the disclosure behaviours section 3.5 already
        # replicates on /Users/Public. So the bodies are compared against the subject's own
        # reading of itself rather than merely counted.
        for label in (
            "a non-administrator names another non-administrator",
            "a non-administrator names an ADMINISTRATOR  (009 T2's cell)",
        ):
            status, _, payload = answers[label]
            if status != 200:
                probe.observe(f"BODY  {label}", "refused, so there is nothing to disclose")
                continue
            document = body_of(payload)
            probe.observe(
                f"BODY  {label}",
                f"{len(document)} properties; Configuration "
                f"{'PRESENT' if 'Configuration' in document else 'absent'}, Policy "
                f"{'PRESENT' if 'Policy' in document else 'absent'}"
                + (
                    f", Policy.IsAdministrator={document['Policy'].get('IsAdministrator')!r}"
                    if isinstance(document.get("Policy"), dict)
                    else ""
                ),
            )

        # Byte-for-byte against the administrator's own reading of the same user: if the two
        # agree, the route has no per-caller redaction at all, which is what decides whether
        # Atrium may serve one representation to everybody.
        stolen = answers["a non-administrator names an ADMINISTRATOR  (009 T2's cell)"]
        owner = server.get_raw(f"/Users/{server.user_id}")
        probe.observe(
            "the administrator's object, as read by the reader vs by themselves",
            "identical bytes" if stolen[2] == owner[2] else "DIFFERENT bytes",
        )
    finally:
        for user_id in made:
            removed, _, payload = server.delete_raw(f"/Users/{user_id}")
            if removed not in (200, 204):
                probe.note(
                    f"could not delete throwaway user {user_id}: {removed} {payload[:80]!r} - "
                    "remove it by hand"
                )
        probe.observe("throwaway users deleted", len(made))

    refused = {
        label: answered[0]
        for label, answered in answers.items()
        if label.startswith("a non-administrator names")
    }
    stranger = refused["a non-administrator names another non-administrator"]
    probe.conclude(
        f"a non-administrator naming another user is answered {stranger}; the full matrix is "
        "above, and the BODY rows say whether a 200 is a disclosure",
        matches_documentation=stranger == 403,
    )
    return probe


if __name__ == "__main__":
    raise SystemExit(main(run, __doc__.splitlines()[0], needs_writes=True))
