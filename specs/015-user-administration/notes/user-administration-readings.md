# 015 — what a Jellyfin answers when an administrator makes, restricts and removes an account

`[probe: tools/probe_user_administration.py, Jellyfin 10.11.11, 2026-09-16]`

The question was 015's eight readings — OQ-1, OQ-4, OQ-5, OQ-6 and OQ-8 to OQ-11 — and the place
they could be asked was fixed before any of them: **every one of them writes**, and the operator's
own server answers `12.0.0` since 2026-09-12, so a reading taken there is not a reading of the
pinned contract. The probe stands up the pinned image with one `movies` library over the fixture's
`Movies` directory, walks the five operations as the instance's own administrator, and destroys the
instance and its volumes, including on failure.

**Four runs, and the reason there were four is the point of this note.** One died before answering
— the `SIGILL` start [010 plan §7](../../010-conformance-harness/plan.md) measured at four in eight
— and after each of the other three a close reading moved something:

| run | what it moved |
|---|---|
| 1 | Two of its own readings were the probe's fault. The `404` for an absent account sat behind a `400`, because the body it sent was partial and model validation fires first; and the check that the administrator could still sign in signed in **from the administrator's own device**, which revoked the token the teardown needed |
| 2 | The absent account was still not absent: the all-zeros identifier is the one the reference refuses *before* it looks anything up. And the `401` at cleanup turned out not to be a probe defect at all — it is the finding of OQ-11 |
| 3 | Killed. The `OQ-5` battery it was running could not tell *kept* from *reset*, because every property it omitted was already sitting on its own default |
| 4 | The readings below |
| 5 | **The verification run.** The spec was amended to what run 4 read, the probe's stated expectation was moved with it, and the run came back `OK documentation confirmed` — so every reading cited here is one the script as committed reproduces against the pinned image |

## Readings

### The account a creation makes

```
POST /Users/New, valid                          200, and the document carries
                                                ['Configuration', 'EnableAutoLogin', 'HasConfiguredEasyPassword',
                                                 'HasConfiguredPassword', 'HasPassword', 'Id', 'Name', 'Policy', 'ServerId']
the default policy                              42 properties
the default configuration                       15 properties
  IsHidden                                      true      ← a new account is not on a login screen
  IsDisabled / IsAdministrator                  false / false
  EnableAllFolders                              true      ← and EnabledFolders is []
  LoginAttemptsBeforeLockout                    -1
  MaxActiveSessions                             0
GET /Users, in the order it answered            ['atrium-probe-password-null', 'atrium-probe-policy',
                                                 'atrium-reference-admin']   ← by name
```

`IsHidden: true` reproduces 002 §3.4's own reading `[probe: tools/probe_public_users.py, Jellyfin
10.11.11, 2026-09-02]`, from the other side: `/Users/Public` answered `[]` throughout this run,
with three accounts on the server.

### OQ-1 — the refusals, and there are four envelopes rather than one

```
a name that is empty                            400 application/json  {"type":"…#section-15.5.1","title":"One or more
                                                validation errors occurred.","status":400,
                                                "errors":{"Name":["The Name field is required."]},"traceId":"…"}
a name that is whitespace ("   ")                400  the same body, keyed on Name
a name holding "/"                              400 text/plain  Error processing request.
a name holding ":"                              400 text/plain  Error processing request.
a name with a leading space                     400 text/plain  Error processing request.
a name with a trailing space                    400 text/plain  Error processing request.
a name another account holds exactly            400 text/plain  Error processing request.
a name another account holds in another case    400 text/plain  Error processing request.
a body with no Name                             400 application/json  …"errors":{"$":["JSON deserialization for type
                                                'Jellyfin.Api.Models.UserDtos.CreateUserByName' …"]}
no body at all                                  415 application/json  {"title":"Unsupported Media Type","status":415,…}
a body that is not an object ([])                400 application/json  …"errors":{"$":["The JSON value could not be
                                                converted to Jellyfin.Api.Models…"]}
GET /Users?isHidden=banana                      400 application/json  …"errors":{"isHidden":["The value 'banana' is
                                                not valid."]}
```

**The message the source carries never reaches the wire.** `ThrowIfInvalidUsername` raises with a
sentence listing which characters a name may hold, and `CreateUserAsync` raises with *"A user with
the name '…' already exists."*
`[source: Jellyfin.Server.Implementations/Users/UserManager.cs:296-315, 900-908 @ v10.11.11]` —
and both arrive as the **same six words**, `Error processing request.`, in `text/plain`. A client
cannot tell an invalid name from one already taken, and neither can an operator.

**An empty name is not the same refusal as an invalid one.** Empty and whitespace are caught by
model validation before the route runs, and keyed on `Name`; everything else reaches the manager
and comes back as the opaque `400`. **And no body at all is `415`, not `400`.**

**Not one of the eight refusals left an account behind**: the count on `GET /Users` was unchanged
after every one of them (OQ-4).

### OQ-4 — a creation cannot fail after the account exists, from here

```
a creation with a null password                 200, HasPassword false, HasConfiguredPassword false
```

The reference commits the account and *then* sets the password, so the shape 015 §3.2 asks about is
real — but the second step takes any string the body carries and skips a `null` one, and nothing
this probe could send made it fail. **Recorded as not reachable rather than as impossible.**

### OQ-5 — the policy body is a whole document, and two of its properties are required

```
a body naming one property ({"IsAdministrator": false})
                                                400 application/json  …"errors":{"PasswordResetProviderId":
                                                ["The PasswordResetProviderId field is required."]}
an empty body ({})                               400  the same
a body that is not an object ([])                400 application/json  …"The JSON value could not be converted to
                                                MediaBrowser.Model…"
no body at all                                  415 application/json  Unsupported Media Type
```

and with a **whole** document, one property left out at a time — each one first moved **off** its
own default, which is what run 3 could not do:

```
EnableAllFolders left out                       204 → true   (it was false; the default is true)
EnableMediaPlayback left out                    204 → true   (it was false; the default is true)
LoginAttemptsBeforeLockout left out             204 → -1     (it was 7;     the default is -1)
MaxActiveSessions left out                      204 → 0      (it was 3;     the default is 0)
EnableContentDownloading left out               204 → true   (it was false; the default is true)
PasswordResetProviderId left out                400  required
AuthenticationProviderId left out               400  required
```

**So the body is a replacement and not a patch**, which is what 015 §3.3 said — an omitted property
takes the type's default and does not keep what was stored. The two provider identifiers are the
exception: leaving either out is refused rather than defaulted.

```
a policy carrying a property the reference has never heard of
                                                204, and it does not come back
```

### The four refusals of §3.3 — two hold, one was undeclared, one is unreachable

```
a whole policy for an account that does not exist   404 application/json  {"title":"Not Found","status":404,…}
the same, for the all-zeros identifier              400 text/plain  Error processing request.
a partial body for that same absent account         400 application/json  keyed on PasswordResetProviderId
a whole policy for an identifier that is not one    400 application/json  …"errors":{"userId":["The value
                                                    'not-an-identifier' is not valid."]}
demoting the only administrator                     403 application/json  "There must be at least one user in the
                                                    system with administrative access."
disabling an administrator                          403 application/json  "Administrators cannot be disabled."
the administrator's policy after both refusals      IsAdministrator=true IsDisabled=false
```

The `404` is real and **the pinned document does not declare it** `[spec: UpdateUserPolicy]`. The
all-zeros identifier answers something else entirely, which is the shape 009 met on `POST
/Playlists`. The two `403` bodies are JSON-encoded bare strings — [behaviours
§1.11](../../../docs/compatibility/behaviours.md#111-there-are-four-error-shapes-not-one)'s fourth
shape.

**The third guard was not reached**, and the reason is the second one: *"there must be at least one
enabled user"* fires only when the account being disabled is the last enabled one, and on a server
reached from a running start that account is an administrator — which the guard above refuses
first.

### OQ-6 — what a disabling revokes

```
the seat holds a token                          200 on GET /Users/Me
disabling a non-administrator                   204
the token it was holding, afterwards            401
signing in again, afterwards                    403
GET /Users?isDisabled=true                      ['atrium-probe-disable']
GET /Users/Public                               []
```

### OQ-8 — what `ResetPassword` leaves

```
ResetPassword: true on another account          204
HasPassword / HasConfiguredPassword             false / false
signing in with no password                     200          ← anybody who knows the name
signing in with the old password                401
```

### OQ-9 — the asymmetry is real, and it is on the wire

```
an administrator changes another's, no CurrentPw        204   (old password 401, new password 200)
the account changes its own, wrong CurrentPw            403 application/json  "Invalid user or password entered."
a non-administrator changes an administrator's          403 application/json  "User is not allowed to update the
                                                        password."
an administrator naming ITSELF in userId, no CurrentPw  403 application/json  "Invalid user or password entered."
the same administrator OMITTING userId, no CurrentPw    204
```

**Two identical requests but for a query parameter naming the caller's own account**, and one is
refused. 015 §3.4 read that off the condition's shape and it is reproduced here.

### OQ-10 — what a deletion takes with it

```
the seat owns two playlists, one private and one public
DELETE /Users/{id} on the owner                 204
the private playlist, read by the administrator 404 application/json  {"title":"Not Found","status":404,…}
the public playlist, read by the administrator  200  — it is still there, and its owner is not
deleting the same account twice                 404
the seat's token afterwards                     401
```

### OQ-11 — the last administrator cannot delete itself, and the refusal is not free

```
an administrator deletes its own, and only, account     400 text/plain  Error processing request.
the token this run was holding, after the refusal       401
GET /Users/Public afterwards                            200  []
signing in as it afterwards                             200
```

**There is a guard, and it is not in the controller.** 015 §3.5 read `DeleteUser` and found no check
that an administrator is left `[source: Jellyfin.Api/Controllers/UserController.cs:155-167 @
v10.11.11]`, which was right about that method and wrong about the server: the refusal comes from
below it and arrives as the same opaque `400` an invalid name does.

**And the controller had already done two of its three steps before the refusal.** It revokes every
token the account holds and removes its playlists *before* calling the manager that raises — so a
deletion that was refused still signed the administrator out, on a server where it is the only one.
The account survives and can sign in again, so nothing is lost; but the first two runs of this
probe reported this as a cleanup failure, an account left behind under a revoked token, before it
was read as what it is.
