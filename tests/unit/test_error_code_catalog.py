"""`docs/error-codes.json` is a published contract, so it must not drift.

Four agent services keep a copy of that file as a test fixture and assert their
own error-code maps against it. Without this test a renamed code ships green and
surfaces only as an agent telling a caller "something went wrong".
"""

import json
from typing import cast

import pytest

from src.app.cli.export_error_codes import CATALOG_PATH, build_catalog, catalog_from
from src.app.exceptions.base import BaseAppException


def test_the_committed_catalog_matches_the_exception_classes() -> None:
    committed = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))

    assert committed == build_catalog(), (
        "docs/error-codes.json is out of date. Regenerate it with: python -m src.app.cli.export_error_codes"
    )


def test_two_classes_sharing_a_code_are_refused() -> None:
    # Built with type() and cast rather than by subclassing BaseAppException:
    # a real subclass would stay in __subclasses__() for the rest of the session
    # and break the drift test above.
    attributes = {"error_code": "duplicated", "status_code": 409, "default_detail": "."}
    classes = [cast(type[BaseAppException], type(name, (), attributes)) for name in ("First", "Second")]

    with pytest.raises(ValueError, match="Duplicate error_code 'duplicated'"):
        catalog_from(classes)
