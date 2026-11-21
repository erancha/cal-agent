"""The process log keeps each model call's line whatever level it runs at."""

import logging
from collections.abc import Iterator

import pytest

from calagent.adapters.model_costs import MODEL_CALL_LOGGER
from calagent.platform.logging import configure_logging


@pytest.fixture
def restore_logging() -> Iterator[None]:
    """Undo configure_logging's process-wide changes so later tests see pytest's setup."""
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    model_call = logging.getLogger(MODEL_CALL_LOGGER)
    saved_model_call_level = model_call.level
    yield
    root.handlers[:] = saved_handlers
    root.setLevel(saved_level)
    model_call.setLevel(saved_model_call_level)


@pytest.mark.usefixtures("restore_logging")
def test_model_call_lines_pass_a_warning_level_log() -> None:
    configure_logging("WARNING", "WARNING")

    assert logging.getLogger(MODEL_CALL_LOGGER).isEnabledFor(logging.INFO)
    assert not logging.getLogger("calagent").isEnabledFor(logging.INFO)
