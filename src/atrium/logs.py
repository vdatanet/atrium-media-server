# SPDX-License-Identifier: GPL-3.0-or-later
"""What this server writes down, and the two things it must not.

Both were found by the test in tests/security rather than by reading, and both are **library
defaults** rather than anything this project wrote - which is why they were invisible.

**SQLAlchemy logs every statement and its bound parameters** as soon as its logger is enabled for
`INFO`, and `logging.basicConfig(level=INFO)` enables it. The bound parameters of the statements
this feature runs are password hashes and token hashes. So the engine's logger is set to `WARNING`
explicitly: an operator who wants SQL echoed turns it on deliberately, which is the only way that
should ever happen.

**A token travels in a URL.** `?api_key=` and `?ApiKey=` are two of the five mechanisms
(spec section 3.1), and they exist because an image loader and an external player are handed a URL
and set no headers - so the credential is in the request line, which is the field an access log
exists to record. Redacting it costs one filter and leaves the log useful: the path, the status and
the method are all still there.

Neither is a compatibility question. A log is not a surface a client can observe, so Principle I is
silent and this is a decision made on its merits.
"""

from __future__ import annotations

import logging
import re

#: The query parameters that carry a credential. Matched case-insensitively, because the two
#: spellings differ only in case and a third would be a client's typo rather than a mechanism.
CREDENTIAL_QUERY = re.compile(r"\b(api_key|ApiKey)=([^&\s\"']+)", re.IGNORECASE)

REDACTED = "REDACTED"

#: Libraries that log more than an operator asked for. The engine logger is the one that matters:
#: at `INFO` it writes every statement and every bound parameter, and this feature's parameters are
#: hashes of credentials.
NOISY = ("sqlalchemy.engine", "sqlalchemy.pool", "sqlalchemy.orm")


class RedactCredentials(logging.Filter):
    """Replace a token in a URL with `REDACTED`, wherever the record came from.

    Rewrites the record rather than dropping it: an access log without the request is not a log.
    The formatted message is checked first, so a record that carries no credential keeps its lazy
    arguments and costs one regular expression that does not match.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # a record that cannot format is not one to rewrite
            return True
        if not CREDENTIAL_QUERY.search(message):
            return True
        record.msg = CREDENTIAL_QUERY.sub(rf"\1={REDACTED}", message)
        record.args = ()
        return True


def configure(level: int = logging.INFO) -> None:
    """The logging an Atrium server ships with. Called by the entry point, and by its test."""
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)-7s %(message)s")

    redact = RedactCredentials()
    root = logging.getLogger()
    if not any(isinstance(existing, RedactCredentials) for existing in root.filters):
        root.addFilter(redact)
    for handler in root.handlers:
        if not any(isinstance(existing, RedactCredentials) for existing in handler.filters):
            handler.addFilter(redact)

    for name in NOISY:
        logging.getLogger(name).setLevel(logging.WARNING)


__all__ = ["CREDENTIAL_QUERY", "NOISY", "REDACTED", "RedactCredentials", "configure"]
