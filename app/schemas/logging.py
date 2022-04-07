"""Logging module."""
from pathlib import Path

from pydantic import BaseModel


class LoggingBase(BaseModel):
    """Base logging model."""

    path: Path
    level: str
    enqueue: bool
    retention: str
    rotation: str
    format_: str


class LoggerModel(BaseModel):
    """Logger model."""

    logger: LoggingBase
