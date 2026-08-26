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

## Reading one

They are single-line and compact — no spaces after `:` or `,` — because that is what goes on the
wire, in the reference and here. Key order is part of the file for the same reason. Format one for
reading with `python3 -m json.tool`, but do not commit the result: a reformatted golden compares
byte-unequal against every response the server produces.

There is no trailing newline. The file is the body, and the body does not end in one.

## `{data-dir}`

One value is substituted before comparison: the instance's data directory, which is a temporary
directory and different on every run. Everything else that could vary between two machines is
**pinned at its source** by the fixture — the server identity comes from a `state.json` written
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
