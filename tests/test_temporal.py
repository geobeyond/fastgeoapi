"""The OGC ``datetime`` type: an instant or an interval of RFC 3339 values."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError

from app.schemas.temporal import OgcDatetime, TimeInterval

ADAPTER = TypeAdapter(OgcDatetime)


@pytest.mark.parametrize(
    ("text", "instant"),
    [
        ("2020-05-01T10:00:00Z", datetime(2020, 5, 1, 10, tzinfo=UTC)),
        ("2020-05-01T12:00:00+02:00", datetime(2020, 5, 1, 10, tzinfo=UTC)),
        ("2020-05-01T10:00:00", datetime(2020, 5, 1, 10, tzinfo=UTC)),
        ("2020-05-01", datetime(2020, 5, 1, tzinfo=UTC)),
        ("2020-05-01t10:00:00z", datetime(2020, 5, 1, 10, tzinfo=UTC)),
    ],
)
def test_an_instant_is_a_datetime_in_utc(text, instant):
    parsed = ADAPTER.validate_python(text)

    assert parsed == instant
    assert parsed.utcoffset() == timedelta(0)


@pytest.mark.parametrize(
    ("text", "interval"),
    [
        (
            "2020-05-01T10:00:00Z/2020-05-02T10:00:00Z",
            (datetime(2020, 5, 1, 10, tzinfo=UTC), datetime(2020, 5, 2, 10, tzinfo=UTC)),
        ),
        ("2020-05-01T10:00:00Z/..", (datetime(2020, 5, 1, 10, tzinfo=UTC), None)),
        ("2020-05-01T10:00:00Z/", (datetime(2020, 5, 1, 10, tzinfo=UTC), None)),
        ("../2020-05-01T10:00:00Z", (None, datetime(2020, 5, 1, 10, tzinfo=UTC))),
    ],
)
def test_an_interval_has_none_for_an_open_end(text, interval):
    parsed = ADAPTER.validate_python(text)

    assert isinstance(parsed, TimeInterval)
    assert (parsed.start, parsed.end) == interval


def test_a_date_that_ends_an_interval_covers_its_whole_day():
    parsed = ADAPTER.validate_python("2020-05-01/2020-05-31")

    assert isinstance(parsed, TimeInterval)
    assert parsed.start == datetime(2020, 5, 1, tzinfo=UTC)
    assert parsed.end == datetime(2020, 5, 31, 23, 59, 59, 999999, tzinfo=UTC)


@pytest.mark.parametrize(
    "text",
    [
        "yesterday",
        "2020-13-01",
        "1700000000",
        "2020-05-01/2020-05-02/2020-05-03",
        "2020-05-02/2020-05-01",
        "../..",
        "/",
        "20200501",
        "2020-W01-1",
        "2020-05-01T10:00",
        "2020-05-01 10:00:00Z",
        "0001-01-01T00:00:00+01:00",
        "9999-12-31T23:59:59-01:00",
        "2020-05-01T10:00:00+02:60",
        "2020-05-01T10:00:00+24:00",
    ],
)
def test_a_value_that_is_not_an_instant_or_an_interval_is_refused(text):
    with pytest.raises(ValidationError):
        ADAPTER.validate_python(text)


def test_a_value_that_is_not_text_is_refused():
    with pytest.raises(ValidationError):
        ADAPTER.validate_python(1_700_000_000)


def test_the_type_works_as_a_model_field_from_json():
    class Request(BaseModel):
        datetime: OgcDatetime | None = None

    request = Request.model_validate_json('{"datetime": "2020-05-01/.."}')

    assert request.datetime == TimeInterval(datetime(2020, 5, 1, tzinfo=UTC), None)


def test_the_json_schema_is_a_string():
    schema = ADAPTER.json_schema()

    assert schema["type"] == "string"
    assert "description" in schema
