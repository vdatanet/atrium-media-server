# SPDX-License-Identifier: GPL-3.0-or-later
"""`atrium-admin` - the command-line client an operator sets a server up with.

**A client, and nothing more.** It reaches the server through the operations any client has - the
four of 014 spec section 3.8 and the two it borrows from 001 and 002 - and **imports nothing from
`atrium` outside this package**, so it cannot read the store or the configuration by accident.
`tests/unit/test_import_directions.py` holds both directions: nothing here imports the server, and
nothing in the server imports this.

`client.py` is the HTTP half, one method per operation; `commands.py` is the program - arguments,
passwords, output and exit codes.

See specs/014-first-time-setup/spec.md section 3.8 and plan.md section 6.7.
"""
