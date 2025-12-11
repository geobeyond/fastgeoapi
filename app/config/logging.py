"""Logging module."""

import logging
import sys
from pathlib import Path

from loguru import logger

from app.config.app import configuration as cfg
from app.schemas.logging import LoggerModel, LoggingBase


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


def create_logger(name: str):
    """Create a logger instance."""
    logger = logging.getLogger(name)
    config = LoggerModel(
        logger=LoggingBase(
            path=Path(cfg.LOG_PATH) / cfg.LOG_FILENAME,
            level=cfg.LOG_LEVEL,
            enqueue=cfg.LOG_ENQUEUE,
            retention=cfg.LOG_RETENTION,
            rotation=cfg.LOG_ROTATION,
            format_=cfg.LOG_FORMAT,
        ),
    )
    logger = CustomizeLogger.make_logger(config)

    return logger
