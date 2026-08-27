# Golden responses

The exact bytes a client receives, checked in. One file per response, compared byte for byte by
[`tests/conformance/golden.py`](../conformance/golden.py) — never parsed first, because casing,
`null`-versus-absent and integer-versus-string are the contract and all three vanish after parsing.
The levels this serves are defined in
[docs/compatibility/conformance.md](../../docs/compatibility/conformance.md#l1--shape).

| File | Response |
|---|---|
| `System.Info.Public.json` | `GET /System/Info/Public` — unauthenticated |
| `System.Info.json` | `GET /System/Info` — authenticated |
| `System.Ping.json` | `GET /System/Ping` and `POST /System/Ping`, which answer identically |
| `System.Info.Public.CamelCase.json` | The same response under `profile="CamelCase"` |
| `Users.AuthenticateByName.json` | `POST /Users/AuthenticateByName` |
| `Users.Public.json` | `GET /Users/Public` — unauthenticated, and it carries `Configuration` and `Policy` |
| `Users.Me.json` | `GET /Users/Me` |
| `Users.Me.CamelCase.json` | The same, under `profile="CamelCase"` — the profile reaches **inside** `Policy` and `Configuration` |
| `Users.ById.json` | `GET /Users/{userId}` |
| `Users.Configuration.json` | `POST /Users/Configuration` — **empty**, because a `204` has no body |
| `Sessions.json` | `GET /Sessions` |
| `Sessions.Capabilities.Full.json` | `POST /Sessions/Capabilities/Full` — **empty**, for the same reason |

## Reading one

They are single-line and compact — no spaces after `:` or `,` — because that is what goes on the
wire, in the reference and here. Key order is part of the file for the same reason. Format one for
reading with `python3 -m json.tool`, but do not commit the result: a reformatted golden compares
byte-unequal against every response the server produces.

There is no trailing newline. The file is the body, and the body does not end in one.

## An empty file

`Users.Configuration.json` and `Sessions.Capabilities.Full.json` are zero bytes, and that is the
statement: those routes answer `204` and a body there would be a difference a client can see.

## The placeholders

One value is substituted in the 001 responses: the instance's data directory, which is a temporary
directory and different on every run. Feature 002 adds three, and only where a value is unstable by
construction rather than merely inconvenient — `{access-token}` and `{session-id}` are random and
would be useless if they were not, and `{date}` appears in the two responses that report a
timestamp as it happens. Four of 002's eight goldens have **no placeholder at all**: the dates are
written before the response is read, so they are pinned like everything else.

**What a placeholder gives up, an assertion takes back.** A substituted value cannot fail a
comparison, so each is format-checked before it is replaced — 32 lowercase hex for a token or a
session, seven fractional digits and a `Z` for a date. Otherwise `AccessToken` could become an
integer and the golden would still pass.

Everything else that could vary between two machines is **pinned at its source** by the fixture — the server identity comes from a `state.json` written
before the server starts, `LocalAddress` is derived from the request, and the host architecture is
fixed — so that the golden records real values in real positions rather than a row of placeholders.
The reasoning for each is in [`test_golden.py`](../conformance/test_golden.py).

## Changing one

```bash
uv run pytest --update-golden
```

The run then prints what it rewrote. **Read the diff.** A change here is a change to what every
client receives, and it is reviewed as one — which is the only reason regenerating them is allowed
to be this easy.
