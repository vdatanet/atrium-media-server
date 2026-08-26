# ADR-0006 — Password hashing

**Status:** Accepted · **Date:** 2026-08-26

## Context

Feature 002 stores user passwords. The reference uses **PBKDF2-SHA512**, 210,000 iterations, a
16-byte salt and a 64-byte output, serialised as
`$PBKDF2-SHA512$iterations=210000$<SALT-HEX>$<HASH-HEX>`.
`[source: Emby.Server.Implementations/Cryptography/CryptographyProvider.cs:16-34,
MediaBrowser.Model/Cryptography/Constants.cs:11-21 @ v10.11.11]`

The question is whether Atrium should match it.

**It is not part of the contract.** A password hash never reaches a client. Principle I does not
apply, and there is no compatibility argument in either direction — which is unusual for this
project and worth stating explicitly, because the reflex here is to match the reference.

That leaves the choice to be made on its own merits, and the merits are security ones.

## Decision

**Argon2id**, through `argon2-cffi`, with parameters recorded in the stored string so they can be
raised without invalidating existing passwords.

**Stored format** — self-describing, algorithm first, so a future migration is a parse rather than
a guess:

```
$argon2id$v=19$m=<memory>,t=<time>,p=<parallelism>$<salt>$<hash>
```

**Rehash on successful login.** When a password verifies against a record whose algorithm or
parameters are below the current policy, the record is rewritten with the current ones. This is the
only moment the plaintext is available, and it is what lets parameters be raised without a mass
reset or a migration that cannot work.

**Access tokens are hashed too**, with plain SHA-256 rather than a KDF: they are 128 bits of
generated entropy, not a human-chosen secret, so there is nothing to brute-force and no reason to
pay a KDF's cost on every authenticated request. Lookup is by hash. A leaked database then does not
hand over live sessions.

## Consequences

- One dependency, `argon2-cffi`, which is widely deployed and maintained. It is the project's only
  cryptographic dependency and its only one with a compiled component.
- Verification is deliberately expensive, which is the point, and it costs on the login path only —
  token verification is a hash lookup.
- **Authentication must run the KDF even when the username does not exist**, against a dummy
  record, or the response time discloses which usernames are real. This is a plan-level requirement
  in 002, and it follows from the choice of an expensive KDF rather than being independent of it.
- Parameters live in configuration with sane defaults, and moving them is safe because of the
  rehash-on-login rule.
- **Importing a Jellyfin user database is not possible**, since Atrium cannot verify a PBKDF2
  record. This is not a goal — see the alternatives — but it is a door this decision closes and it
  should not be discovered later.

## Alternatives rejected

**Match the reference: PBKDF2-SHA512 at 210,000 iterations.** The only real argument is that it
would allow importing an existing Jellyfin user database. That is not a v1 goal, it is a one-time
operation for a small number of rows that a user can redo by resetting passwords, and it would fix
this project to a KDF that is chosen for backward compatibility rather than for strength. PBKDF2 is
not broken; it is simply the weaker choice against attackers with parallel hardware, which is
exactly the threat a password hash exists to resist.

**`hashlib.scrypt`, from the standard library.** Genuinely tempting: memory-hard, no dependency,
and the rest of the project's tooling is deliberately dependency-free. It loses on two counts.
Argon2id is the current recommendation and has parameters that are easier to reason about; and the
dependency-free rule was adopted for the **probe scripts**, which must run before an environment
exists, not for the server, which has an environment by definition.

**bcrypt.** Mature and widely used, and it silently truncates the password at 72 bytes — a
foot-gun that has produced real vulnerabilities, and one nobody should have to remember.

**Delegating to an external identity provider.** Out of v1 scope, and it would not remove the need
to store *something* for local accounts.
