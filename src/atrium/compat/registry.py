# SPDX-License-Identifier: GPL-3.0-or-later
"""Finding every model the project will serialise.

The conformance sweeps walk the model registry rather than the router, so a model is checked
whether or not a route returns it yet. A sweep that only sees routed models would let a wrong
field name sit unnoticed until the day someone wires it up.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Iterator

from atrium.compat.model import AtriumModel

#: Packages whose modules are imported before walking, so their models register themselves.
MODEL_PACKAGES = ("atrium.api",)


def import_model_modules() -> None:
    """Import every module that may define a model, so subclasses exist to be found."""
    for package_name in MODEL_PACKAGES:
        package = importlib.import_module(package_name)
        for module in pkgutil.walk_packages(package.__path__, prefix=f"{package_name}."):
            importlib.import_module(module.name)


def iter_models() -> Iterator[type[AtriumModel]]:
    """Every AtriumModel subclass, transitively, without duplicates."""
    seen: set[type[AtriumModel]] = set()

    def walk(cls: type[AtriumModel]) -> Iterator[type[AtriumModel]]:
        for subclass in cls.__subclasses__():
            if subclass not in seen:
                seen.add(subclass)
                yield subclass
                yield from walk(subclass)

    yield from walk(AtriumModel)


__all__ = ["import_model_modules", "iter_models"]
