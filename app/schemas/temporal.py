"""The OGC ``datetime`` parameter as a pydantic type."""

import re
from datetime import UTC, date, datetime, time
from typing import Annotated, NamedTuple

from pydantic import PlainValidator, WithJsonSchema

# RFC 3339, section 5.6, case-insensitive: a full-date, or a date-time whose
# offset may be missing.
_FULL_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_DATE_TIME = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})?"
)


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

    Each end is an RFC 3339 full-date or date-time, in either case::

        2020-05-01T12:00:00+02:00  2020-05-01T10:00:00+00:00
        2020-05-01t10:00:00        2020-05-01T10:00:00+00:00
        2020-05-01                 2020-05-01T00:00:00+00:00
        2020-05-01/..              TimeInterval(2020-05-01T00:00:00+00:00, None)
        ../2020-05-31              TimeInterval(None, 2020-05-31T23:59:59.999999+00:00)

    An open end, ``..`` or empty, is None, and only one end can be open.

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
        interval of them, or out of range once in UTC; or its interval is
        open at both ends or starts after it ends.
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
    text = value.upper()
    if _FULL_DATE.fullmatch(text):
        parse = date.fromisoformat
    elif _DATE_TIME.fullmatch(text):
        parse = datetime.fromisoformat
    else:
        raise ValueError(f"datetime is not an RFC 3339 date or date-time: {value}")
    try:
        parsed = parse(text)
        if not isinstance(parsed, datetime):
            return datetime.combine(parsed, time.max if end_of_day else time.min, tzinfo=UTC)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except ValueError:
        raise ValueError(f"datetime is not a date of the calendar: {value}") from None
    except OverflowError:
        raise ValueError(f"datetime is out of range in UTC: {value}") from None


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
