"""Smoke tests — prove the package imports and CI wiring works end to end."""

from pirate_radio import __version__, hello


def test_version_is_a_string() -> None:
    assert isinstance(__version__, str)
    assert __version__


def test_hello_returns_expected_greeting() -> None:
    assert hello() == "pirate-radio online"
