"""The OGC ``datetime`` parameter as a pydantic type."""

from datetime import UTC, date, datetime, time
from typing import Annotated, NamedTuple

from pydantic import PlainValidator, WithJsonSchema


class TimeInterval(NamedTuple):
    """An interval of time, with None for an open end.

    Attributes
    ----------
    start
        The first instant, in UTC, or None when the interval has no start.
    end
        The last instant, in UTC, or None when the interval has no end.
        The two are never both None.
    """

    start: datetime | None
    end: datetime | None


def parse_ogc_datetime(value: object) -> datetime | TimeInterval:
    """Parse an OGC ``datetime`` into UTC datetimes.

    An instant gives a datetime; a date alone is its midnight. An interval,
    ``start/end``, gives a TimeInterval whose open end, ``..`` or empty, is
    None; only one end can be open. A date that ends an interval covers its
    whole day. A time without an offset is read as UTC.

    Parameters
    ----------
    value
        The text of the ``datetime`` parameter
        (/req/collections/rc-datetime-definition).

    Returns
    -------
    datetime or TimeInterval
        The instant, or the start and the end of the interval, in UTC.

    Raises
    ------
    ValueError
        The value is not text, not an RFC 3339 date or date-time, not an
        interval of them, or its interval is open at both ends or starts
        after it ends.
    """
    if not isinstance(value, str):
        raise ValueError("datetime is not text")
    if "/" not in value:
        return _parse_instant(value, end_of_day=False)
    start, _, end = value.partition("/")
    if "/" in end:
        raise ValueError(f"datetime is not an instant or an interval: {value}")
    begins = None if start in ("", "..") else _parse_instant(start, end_of_day=False)
    ends = None if end in ("", "..") else _parse_instant(end, end_of_day=True)
    if begins is None and ends is None:
        raise ValueError(f"datetime interval has no start and no end: {value}")
    if begins is not None and ends is not None and begins > ends:
        raise ValueError(f"datetime starts after it ends: {value}")
    return TimeInterval(begins, ends)


def _parse_instant(value: str, *, end_of_day: bool) -> datetime:
    try:
        day = date.fromisoformat(value)
    except ValueError:
        pass
    else:
        return datetime.combine(day, time.max if end_of_day else time.min, tzinfo=UTC)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError(f"datetime is not an RFC 3339 date or date-time: {value}") from None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


OgcDatetime = Annotated[
    datetime | TimeInterval,
    PlainValidator(parse_ogc_datetime),
    WithJsonSchema(
        {
            "type": "string",
            "description": (
                "An RFC 3339 date or date-time, or an interval of them as"
                " start/end with '..' or nothing for one open end."
            ),
        }
    ),
]
"""An instant or an interval of time, parsed into UTC datetimes."""
