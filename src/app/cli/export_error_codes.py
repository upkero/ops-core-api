"""Write `docs/error-codes.json` from the exception hierarchy.

Run with:  python -m src.app.cli.export_error_codes

The exception classes are the single source of truth; the JSON file is a build
artefact that happens to be committed. Four agent services keep a copy of it as
a test fixture and assert their own error-code maps against it, so renaming a
code breaks a test somewhere instead of quietly degrading an agent's message to
the user into "something went wrong".

Scope: only codes carried by a `BaseAppException` subclass. The envelope-level
codes the exception handlers emit for framework failures (`http_error`,
`request_validation_error`, `internal_server_error`) are not in the hierarchy
and are deliberately not invented here — a second source would be the drift this
file exists to prevent.
"""

import json
import pkgutil
from collections.abc import Iterable, Iterator
from importlib import import_module
from pathlib import Path

from src.app import exceptions
from src.app.exceptions.base import BaseAppException

# Repository root: .../src/app/cli/export_error_codes.py
CATALOG_PATH = Path(__file__).resolve().parents[3] / "docs" / "error-codes.json"


def _import_every_exception_module() -> None:
    """Load all modules under `src.app.exceptions`.

    `__subclasses__()` only sees classes that have already been imported, so
    without this walk a new exceptions module would produce a silently
    incomplete catalogue — the one failure mode a generated contract must not
    have.
    """
    for module in pkgutil.iter_modules(exceptions.__path__):
        import_module(f"{exceptions.__name__}.{module.name}")


def _descendants(cls: type[BaseAppException]) -> Iterator[type[BaseAppException]]:
    for subclass in cls.__subclasses__():
        yield subclass
        yield from _descendants(subclass)


def catalog_from(exception_classes: Iterable[type[BaseAppException]]) -> dict[str, dict[str, object]]:
    """Describe the given exception classes, keyed and sorted by error code.

    Split from `build_catalog` so the duplicate check below can be exercised
    without defining a throwaway subclass: `__subclasses__()` registers every
    subclass for the life of the process, so such a class would leak into the
    real catalogue and fail the drift test instead.
    """
    catalog: dict[str, dict[str, object]] = {}
    for exception in exception_classes:
        # Two classes sharing a code would make the catalogue depend on import
        # order, and clients could not tell the two failures apart either.
        if exception.error_code in catalog:
            raise ValueError(
                f"Duplicate error_code {exception.error_code!r}: "
                f"{catalog[exception.error_code]['exception']} and {exception.__name__}"
            )
        catalog[exception.error_code] = {
            "exception": exception.__name__,
            "status_code": exception.status_code,
            "default_detail": exception.default_detail,
        }
    return dict(sorted(catalog.items()))


def build_catalog() -> dict[str, dict[str, object]]:
    """Describe every error code the application can raise."""
    _import_every_exception_module()
    return catalog_from((BaseAppException, *_descendants(BaseAppException)))


def main() -> None:
    CATALOG_PATH.write_text(json.dumps(build_catalog(), indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {CATALOG_PATH}")


if __name__ == "__main__":
    main()
