"""RED tests for ``pirate_radio.logging_setup`` — Phase-4 plan §H / P4-8 (R8′).

``configure_logging`` is the daemon's ONE logging entry: a stdout/journald handler with a
journald-friendly ``levelname name: message`` format, set at the requested level, and **idempotent**
(a restart / re-call must not stack duplicate handlers and double every line). Takes a name or int.
"""

from __future__ import annotations

import logging

from pirate_radio.logging_setup import configure_logging


def _pirate_handlers() -> list[logging.Handler]:
    return [h for h in logging.getLogger().handlers if getattr(h, "_pirate_radio", False)]


def test_sets_the_root_level_from_a_name() -> None:
    configure_logging("DEBUG")
    assert logging.getLogger().level == logging.DEBUG


def test_accepts_an_int_level() -> None:
    configure_logging(logging.WARNING)
    assert logging.getLogger().level == logging.WARNING


def test_is_idempotent_no_duplicate_handlers() -> None:
    configure_logging("INFO")
    configure_logging("INFO")
    configure_logging("INFO")
    assert len(_pirate_handlers()) == 1  # a restart / re-call must not double every log line


def test_installs_a_stdout_handler_with_a_named_format() -> None:
    configure_logging("INFO")
    handlers = _pirate_handlers()
    assert handlers and handlers[0].formatter is not None
    formatted = handlers[0].formatter.format(
        logging.LogRecord("pirate_radio.x", logging.INFO, __file__, 1, "hi", None, None)
    )
    assert "pirate_radio.x" in formatted and "hi" in formatted  # name + message in the line


def test_journald_stream_handler_scrubs_secrets(capsys) -> None:
    # final-review Senior-Dev HIGH: the journald/stdout stream — not only the /logs ring — must
    # scrub a secret embedded in a (third-party) log message before it reaches the operator's eyes.
    configure_logging("INFO")
    logging.getLogger("pirate_radio.x").warning("auth failed: Bearer sk-LEAKED99 rejected")
    out = capsys.readouterr().out
    assert "sk-LEAKED99" not in out  # scrubbed at the sink
    assert "<redacted>" in out
