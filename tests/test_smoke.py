"""Smoke tests — prove the package and its real Phase-0 modules import."""

from pirate_radio import __version__
from pirate_radio.config import load_config
from pirate_radio.errors import PirateRadioError


def test_version_is_a_nonempty_string() -> None:
    assert isinstance(__version__, str)
    assert __version__


def test_core_phase0_symbols_import() -> None:
    assert callable(load_config)
    assert issubclass(PirateRadioError, Exception)
