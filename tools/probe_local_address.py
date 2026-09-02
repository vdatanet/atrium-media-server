#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Does `LocalAddress` advertise HTTPS once a certificate is configured, on an HTTP request?

That is the second of the two prior measurements
[reference-target.md](../docs/compatibility/reference-target.md) has carried open, dated
2026-08-14, and it is the reason [behaviours section 4.2](../docs/compatibility/behaviours.md)
argues a divergence: Atrium reports the scheme it is actually reachable on, and the argument that
no client can observe the difference rests on the override firing **only when a certificate is
configured**. That condition had never been reproduced from this repository, because reproducing
it means installing a certificate and restarting somebody's server.

**It never touches a server somebody owns.** It generates a throwaway self-signed certificate,
stands up a single-use instance of the pinned version with that certificate on its mount, turns
HTTPS on, restarts it so the certificate is read, asks over **plain HTTP**, and destroys
everything - including on failure.

The restart is not incidental. The reference loads its certificate while the host is being built
`[source: Emby.Server.Implementations/ApplicationHost.cs:457-458 @ v10.11.11]` and a configuration
change only validates the new path and asks for a restart
`[source: Emby.Server.Implementations/ApplicationHost.cs:761-764, 779-797 @ v10.11.11]`, so a
server configured in place still answers with the certificate it started without.

Standard library only, on the 3.9 floor, and `--help` starts nothing. It needs `openssl` on the
PATH, because the certificate has to be a PKCS#12 with a private key
`[source: Emby.Server.Implementations/ApplicationHost.cs:600-628 @ v10.11.11]` and the standard
library cannot write one.

Usage:
    python3 tools/probe_local_address.py --allow-writes
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

HERE = Path(__file__).resolve().parent
REPOSITORY = HERE.parent

#: The mounted directory. The certificate goes here because it is the only host path the instance
#: can see, and `reference/` is already git-ignored. Not `tempfile`: a container runtime on macOS
#: does not mount the directory `tempfile` picks, which is `probe_reference_scan.py`'s finding.
TREE = REPOSITORY / "reference" / "certificate-tree"
CERTIFICATE = "reference.pfx"

#: Not a secret: a self-signed certificate this probe generates, uses once, and deletes with the
#: instance. It is here so that the value the configuration carries is readable beside the value
#: the certificate was made with.
CERTIFICATE_PASSWORD = "atrium-reference"  # noqa: S105

#: The configuration key the network settings live under `[spec: GetNamedConfiguration]`.
NETWORK = "network"

DOCUMENT = "docs/compatibility/behaviours.md"
SECTION = "section 2.3, and section 4.2 which rests on it"
EXPECTATION = (
    "behaviours section 2.3: when a certificate is configured the reference advertises the HTTPS "
    "scheme and port in LocalAddress, regardless of the scheme the request came in on"
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


def write_certificate(directory: Path) -> Path:
    """A self-signed PKCS#12 with a private key, which is the only form the reference loads.

    `X509CertificateLoader.LoadPkcs12FromFile`, and it logs *"No private key included"* and
    carries on without a certificate when there is none
    `[source: Emby.Server.Implementations/ApplicationHost.cs:617-621 @ v10.11.11]` - which would
    make this probe measure the *absence* of the override and report parity.
    """
    probe = load("_probe")
    if shutil.which("openssl") is None:
        raise probe.ProbeError(
            "openssl is not on the PATH. The certificate has to be a PKCS#12 carrying a private "
            "key and the standard library cannot write one, so this question cannot be asked "
            "from this machine. Everything else about the probe is standard library only."
        )
    directory.mkdir(parents=True, exist_ok=True)
    key, certificate = directory / "reference.key", directory / "reference.crt"
    bundle = directory / CERTIFICATE
    steps = (
        (
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-subj",
            "/CN=atrium-reference",
            "-keyout",
            str(key),
            "-out",
            str(certificate),
        ),
        (
            "openssl",
            "pkcs12",
            "-export",
            "-inkey",
            str(key),
            "-in",
            str(certificate),
            "-out",
            str(bundle),
            "-passout",
            "pass:" + CERTIFICATE_PASSWORD,
        ),
    )
    for step in steps:
        finished = subprocess.run(  # noqa: S603 - a fixed argument vector, no shell
            step, capture_output=True, text=True, check=False, timeout=120
        )
        if finished.returncode != 0:
            raise probe.ProbeError(
                f"{step[0]} {step[1]} exited {finished.returncode}: {finished.stderr[:400]}"
            )
    return bundle


def local_address(server: Any, path: str) -> str:
    body = server.get(path)
    return str((body or {}).get("LocalAddress", ""))


class Reading:
    """The instance, the certificate, and the two readings either side of the restart."""

    def __init__(self) -> None:
        self.instance: Optional[Any] = None
        self.before = ""
        self.before_authenticated = ""
        self.configuration: Dict[str, Any] = {}

    @contextlib.contextmanager
    def connect(self, args: argparse.Namespace) -> Iterator[Any]:
        probe = load("_probe")
        reference = load("_reference")
        if getattr(args, "server", None):
            raise probe.ProbeError(
                "this probe refuses a server argument. Answering its question means installing a "
                "certificate and restarting the server being asked, which is not something to do "
                "to somebody's installation - so it measures only an instance it creates and "
                "destroys itself (010 spec section 3.1)"
            )
        shutil.rmtree(TREE, ignore_errors=True)
        write_certificate(TREE)
        try:
            # `auto_remove=False`: this run restarts the instance, and a container marked
            # for auto-removal does not survive the stop half of a restart. Measured here
            # first - the first attempt restarted an `--rm` instance and the next request
            # answered `No such container` (Docker 29.4, 2026-09-02).
            spec = reference.InstanceSpec(fixture_root=TREE, libraries=(), auto_remove=False)
            with reference.ReferenceInstance(spec) as instance:
                self.instance = instance
                administrator = instance.administrator
                before = probe.Server(instance.url)
                before.connect(administrator.username, administrator.password, None)
                self.before = local_address(before, "/System/Info/Public")
                self.before_authenticated = local_address(before, "/System/Info")

                self.enable_https(before)
                instance.restart()

                after = probe.Server(instance.url)
                after.connect(administrator.username, administrator.password, None)
                yield after
        except reference.InstanceError as failure:
            raise probe.ProbeError(str(failure)) from failure
        finally:
            shutil.rmtree(TREE, ignore_errors=True)

    def enable_https(self, server: Any) -> None:
        """Turn HTTPS on by sending back the configuration the server itself just gave.

        The whole object, for `POST /Users/{userId}/Policy`'s reason: a named configuration binds
        a complete document `[spec: UpdateNamedConfiguration]`, and a body carrying three keys
        would reset the bind addresses and the published-server settings to their defaults while
        claiming to have changed the certificate.
        """
        module = load("_probe")
        current = server.get(f"/System/Configuration/{NETWORK}")
        if not isinstance(current, dict):
            raise module.ProbeError(
                f"GET /System/Configuration/{NETWORK} did not answer an object: {current!r}"
            )
        updated = dict(current)
        updated["EnableHttps"] = True
        updated["CertificatePath"] = (
            load("_reference").FIXTURE_MOUNT.rstrip("/") + "/" + CERTIFICATE
        )
        updated["CertificatePassword"] = CERTIFICATE_PASSWORD
        server.post(f"/System/Configuration/{NETWORK}", body=updated)
        self.configuration = dict(server.get(f"/System/Configuration/{NETWORK}") or {})

    def report(self, server: Any, _args: argparse.Namespace) -> Any:
        module = load("_probe")
        probe = module.Probe(
            script="probe_local_address.py",
            question=(
                "does LocalAddress advertise the HTTPS scheme and port once a certificate is "
                "configured, on a request that came in over HTTP?"
            ),
            document=DOCUMENT,
            section=SECTION,
            expectation=EXPECTATION,
        )
        anonymous = module.Server(server.base, timeout=server.timeout)
        after = local_address(anonymous, "/System/Info/Public")
        after_authenticated = local_address(server, "/System/Info")

        probe.observe("the request's own scheme", "http (throughout, on both readings)")
        probe.observe("LocalAddress before, /System/Info/Public", self.before or "absent")
        probe.observe("LocalAddress before, /System/Info", self.before_authenticated or "absent")
        probe.observe(
            "configuration stored",
            "EnableHttps={}, CertificatePath={!r}, RequireHttps={}".format(
                self.configuration.get("EnableHttps"),
                self.configuration.get("CertificatePath"),
                self.configuration.get("RequireHttps"),
            ),
        )
        probe.observe(
            "the HTTPS ports the configuration names",
            "InternalHttpsPort={}, PublicHttpsPort={}".format(
                self.configuration.get("InternalHttpsPort"),
                self.configuration.get("PublicHttpsPort"),
            ),
        )
        probe.observe("LocalAddress after, /System/Info/Public", after or "absent")
        probe.observe("LocalAddress after, /System/Info", after_authenticated or "absent")

        overrides = after.startswith("https://") and self.before.startswith("http://")
        probe.conclude(
            (
                f"the override fires: the same route over the same plain-HTTP request answers "
                f"{self.before} before the certificate and {after} after it, so the scheme in "
                f"LocalAddress is the server's configuration and not the request's"
                if overrides
                else f"the override does not fire on this configuration: {self.before!r} before "
                f"and {after!r} after, with EnableHttps="
                f"{self.configuration.get('EnableHttps')} and a certificate at "
                f"{self.configuration.get('CertificatePath')!r}"
            ),
            matches_documentation=overrides,
        )
        probe.note(
            "This is the condition behaviours section 4.2's argument rests on. The divergence is "
            "unobservable exactly while a v1 deployment cannot be in this state - and v1 "
            "terminates no TLS and has no certificate configuration, so it cannot be."
        )
        probe.note(
            "The restart is what makes the reading possible at all. The certificate is read while "
            "the host is built `[source: Emby.Server.Implementations/ApplicationHost.cs:457-458 @ "
            "v10.11.11]`; a configuration change validates the path and asks for a restart "
            "`[source: Emby.Server.Implementations/ApplicationHost.cs:761-764 @ v10.11.11]`. A "
            "probe that configured and asked would measure the server it started as."
        )
        return probe


def main() -> int:
    reading = Reading()
    return int(
        load("_probe").main(
            reading.report,
            description=(
                "Measure whether LocalAddress advertises HTTPS once a certificate is configured "
                "(010 T13, AC-9). Generates a throwaway certificate, stands up a single-use "
                "instance of the pinned version, enables HTTPS, restarts it, asks over plain "
                "HTTP, and destroys everything - including on failure."
            ),
            needs_writes=True,
            with_args=True,
            connect_with=reading.connect,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
