import pytest
from pydantic import ValidationError

from src.app.core.settings.app import AppSettings

KEY = "x" * 16


def test_business_timezone_defaults_to_moscow() -> None:
    assert AppSettings(api_key=KEY, _env_file=None).business_tz.key == "Europe/Moscow"


def test_an_unknown_timezone_fails_validation() -> None:
    with pytest.raises(ValidationError, match="unknown timezone"):
        AppSettings(api_key=KEY, business_timezone="Mars/Olympus")


def test_no_browser_origin_is_allowed_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CORS_ALLOWED_ORIGINS")

    assert AppSettings(api_key=KEY, _env_file=None).cors_allowed_origins == []


def test_slot_window_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        AppSettings(api_key=KEY, slot_window_days=0)
