"""Logging module."""

import logging
import sys
from pathlib import Path

from loguru import logger

from app.schemas.logging import LoggerModel, LoggingBase

# The configured LOG_FORMAT references `extra[request_id]` and `extra[method]`.
# Records emitted without an explicit bind (e.g. plain `logger.info(...)` from
# third-party code or module-level startup logs) would otherwise crash the
# loguru handler with `KeyError: 'request_id'`. Setting defaults via
# `logger.configure(extra=...)` makes those keys always present.
logger.configure(extra={"request_id": None, "method": None})


class InterceptHandler(logging.Handler):
    """Custom logging interceptor."""

    loglevel_mapping = {
        50: "CRITICAL",
        40: "ERROR",
        30: "WARNING",
        20: "INFO",
        10: "DEBUG",
        0: "NOTSET",
    }

    def emit(self, record):
        """Emits a logging record."""
        try:
            level = logger.level(record.levelname).name
        except (AttributeError, ValueError):
            level = self.loglevel_mapping.get(record.levelno, "INFO")

        frame, depth = logging.currentframe(), 2
        while frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        log = logger.bind(request_id="app")
        log.opt(depth=depth, exception=record.exc_info).log(
            level,
            record.getMessage(),
        )


class CustomizeLogger:
    """Handle logger customization."""

    @classmethod
    def make_logger(cls, config: LoggerModel):
        """Create a logger instance."""
        logging_config = config.logger

        logger = cls.customize_logging(
            filepath=logging_config.path,
            level=logging_config.level,
            enqueue=logging_config.enqueue,
            retention=logging_config.retention,
            rotation=logging_config.rotation,
            format=logging_config.format_,
        )
        return logger

    @classmethod
    def customize_logging(
        cls,
        filepath: Path,
        level: str,
        enqueue: bool,
        rotation: str,
        retention: str,
        format: str,
    ):
        """Customize logging configuration."""
        logger.remove()
        logger.add(
            sys.stdout,
            enqueue=enqueue,
            backtrace=True,
            level=level.upper(),
            format=format,
        )
        logger.add(
            str(filepath),
            rotation=rotation,
            retention=retention,
            enqueue=enqueue,
            backtrace=True,
            level=level.upper(),
            format=format,
        )
        logging.basicConfig(handlers=[InterceptHandler()], level=0)
        logging.getLogger("uvicorn.access").handlers = [InterceptHandler()]
        for _log in ["uvicorn", "uvicorn.error", "fastapi"]:
            _logger = logging.getLogger(_log)
            _logger.handlers = [InterceptHandler()]

        return logger.bind(request_id=None, method=None)


# Paths whose access-log lines carry no diagnostic value. On hosts that keep a
# short log buffer (fly.io retains roughly the last hundred lines) the probes —
# which fire every 15-30s once wired into `fly.toml` — are the only thing left
# visible exactly when something has gone wrong and the buffer matters.
PROBE_PATHS = frozenset({"/healthz", "/readyz"})


class ProbeAccessLogFilter(logging.Filter):
    """Drop uvicorn access records for the liveness/readiness probes."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Return False for probe requests, True for everything else."""
        args = record.args
        # uvicorn.access always formats with the 5-tuple
        # (client_addr, method, full_path, http_version, status_code).
        if isinstance(args, tuple) and len(args) == 5:
            return str(args[2]).split("?", 1)[0] not in PROBE_PATHS
        return True


def silence_probe_access_logs() -> None:
    """Attach the probe filter to uvicorn's access logger, idempotently.

    Call this from the application lifespan, not at import time: uvicorn
    applies its own ``dictConfig`` around the app import, and a filter
    attached before that runs is discarded with the rest of the logger
    configuration.
    """
    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, ProbeAccessLogFilter) for f in access_logger.filters):
        access_logger.addFilter(ProbeAccessLogFilter())


def _logging_settings() -> LoggingBase:
    """Where to log, from the configuration if there is one."""
    try:
        from app.config.app import configuration as settings
    except Exception:
        # Not a configured deployment — the CLI editing a document, a
        # test, an import. Importing that module *builds* the settings,
        # so a failure here means nothing from it can be reached: the
        # model's own defaults stand in.
        return LoggingBase()

    return LoggingBase(
        path=Path(settings.LOG_PATH) / settings.LOG_FILENAME,
        level=settings.LOG_LEVEL,
        enqueue=settings.LOG_ENQUEUE,
        retention=settings.LOG_RETENTION,
        rotation=settings.LOG_ROTATION,
        format_=settings.LOG_FORMAT,
    )


def create_logger(name: str):
    """Create a logger instance.

    The settings are read here rather than imported at the top, and a
    failure to build them is not fatal. Almost every module in the
    project asks for a logger while it is being imported, so an eager
    read made *every* import demand a configured fastgeoapi — which is
    how `fastgeoapi config edit` came to require a `HOST` and a `PORT`
    it never uses.

    Falling back is the right behaviour on its own terms because a logger
    that insists on a configured application is a logger that cannot
    report a broken configuration.
    """
    logger = logging.getLogger(name)
    config = LoggerModel(logger=_logging_settings())
    logger = CustomizeLogger.make_logger(config)

    return logger
