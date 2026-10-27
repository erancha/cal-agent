"""Process logging: structlog and standard-library records rendered through one stderr handler.

LOG_LEVEL sets the root level; A2A_LOG_LEVEL sets the SDK's own loggers, which are chatty at
INFO. Uvicorn's loggers are routed to the same handler so every line has one format.
"""

import logging
import sys

import structlog

A2A_LOGGER = "a2a"
UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")

_SHARED_PROCESSORS: list[structlog.typing.Processor] = [
    structlog.contextvars.merge_contextvars,
    structlog.stdlib.add_logger_name,
    structlog.stdlib.add_log_level,
    structlog.processors.TimeStamper(fmt="iso"),
]


def configure_logging(level: str, a2a_level: str) -> None:
    """An unknown level name raises ValueError."""
    structlog.configure(
        processors=[*_SHARED_PROCESSORS, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=_SHARED_PROCESSORS,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.dev.ConsoleRenderer(colors=False),
            ],
        )
    )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    logging.getLogger(A2A_LOGGER).setLevel(a2a_level.upper())
    for name in UVICORN_LOGGERS:
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
