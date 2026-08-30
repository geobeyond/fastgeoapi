"""Logging module."""

import tempfile
from pathlib import Path

from pydantic import BaseModel


class LoggingBase(BaseModel):
    """Base logging model.

    Every field carries the same default the configuration declares, so
    a logger can be built when there is no configuration to read — which
    happens whenever this project is used as a tool rather than run as a
    server, `fastgeoapi config edit` being the case that found it. A
    logger that insisted on a configured application could not report a
    broken configuration.
    """

    path: Path = Path(tempfile.gettempdir()) / "fastgeoapi.log"
    level: str = "info"
    enqueue: bool = True
    retention: str = "1 months"
    rotation: str = "1 days"
    format_: str = (
        "<level>{level: <8}</level> <green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green>"
        " | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan>"
        " - <level>{message}</level>"
    )


class LoggerModel(BaseModel):
    """Logger model."""

    logger: LoggingBase
