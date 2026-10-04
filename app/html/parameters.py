"""The parameters of a collection's items: the ones its data applies, and the form that sets them.

A parameter counts as applied when the provider's ``query()`` uses the
argument pygeoapi passes it in. The table below was read from the code of
pygeoapi 0.24, and a test reads that code again. Providers outside the
table count through the conformance classes they declare.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from pygeoapi.plugin import PLUGINS

from app.html.pages import without_query
from app.pygeoapi.plugin import resolve_provider_class

QUERYABLES = "queryables"
"""Stands for the ``name=value`` parameters, one for each queryable, in the tables below."""

ITEMS_PARAMETERS = frozenset(
    {
        "bbox",
        "bbox-crs",
        "crs",
        "f",
        "lang",
        "limit",
        "offset",
        "resulttype",
        "datetime",
        "sortby",
        "properties",
        "skipGeometry",
        "q",
        "filter",
        "filter-lang",
        "filter-crs",
    }
)
"""The parameters of pygeoapi's items route; any other name is a queryable."""

ALWAYS = frozenset({"f", "lang", "limit", "offset", "resulttype"})
"""What pygeoapi applies itself, whatever the data source."""

_FEATURE_ARGUMENTS = frozenset(
    {"bbox", "datetime_", "properties", "sortby", "select_properties", "skip_geometry"}
)
_SQL_ARGUMENTS = _FEATURE_ARGUMENTS | {"filterq", "crs_transform_spec"}

PROVIDER_ARGUMENTS: dict[str, frozenset[str]] = {
    "pygeoapi.provider.csv_.CSVProvider": frozenset(
        {"bbox", "properties", "select_properties", "skip_geometry"}
    ),
    "pygeoapi.provider.csw_facade.CSWFacadeProvider": frozenset(
        {"bbox", "datetime_", "properties", "sortby", "q"}
    ),
    "pygeoapi.provider.elasticsearch_.ElasticsearchCatalogueProvider": _FEATURE_ARGUMENTS | {"q"},
    "pygeoapi.provider.elasticsearch_.ElasticsearchProvider": _FEATURE_ARGUMENTS | {"q", "filterq"},
    "pygeoapi.provider.erddap.TabledapProvider": frozenset({"bbox", "datetime_"}),
    "pygeoapi.provider.esri.ESRIServiceProvider": _FEATURE_ARGUMENTS | {"crs_transform_spec"},
    "pygeoapi.provider.geojson.GeoJSONProvider": frozenset(
        {"bbox", "properties", "select_properties", "skip_geometry"}
    ),
    "pygeoapi.provider.mongo.MongoProvider": frozenset(
        {"bbox", "datetime_", "properties", "sortby", "skip_geometry"}
    ),
    "pygeoapi.provider.mvt_postgresql.MVTPostgreSQLProvider": _SQL_ARGUMENTS,
    "pygeoapi.provider.ogr.OGRProvider": frozenset(
        {"bbox", "properties", "skip_geometry", "crs_transform_spec"}
    ),
    "pygeoapi.provider.opensearch_.OpenSearchCatalogueProvider": _FEATURE_ARGUMENTS | {"q"},
    "pygeoapi.provider.opensearch_.OpenSearchProvider": _FEATURE_ARGUMENTS | {"q", "filterq"},
    "pygeoapi.provider.oracle.OracleProvider": _SQL_ARGUMENTS | {"q"},
    "pygeoapi.provider.parquet.ParquetProvider": _FEATURE_ARGUMENTS - {"sortby"},
    "pygeoapi.provider.sensorthings.SensorThingsProvider": _FEATURE_ARGUMENTS,
    "pygeoapi.provider.socrata.SODAServiceProvider": _FEATURE_ARGUMENTS,
    "pygeoapi.provider.sql.GenericSQLProvider": _SQL_ARGUMENTS,
    "pygeoapi.provider.sql.MySQLProvider": _SQL_ARGUMENTS,
    "pygeoapi.provider.sql.PostgreSQLProvider": _SQL_ARGUMENTS,
    "pygeoapi.provider.sqlite.SQLiteGPKGProvider": frozenset(
        {"bbox", "properties", "skip_geometry"}
    ),
    "pygeoapi.provider.tinydb_.TinyDBCatalogueProvider": frozenset(
        {"bbox", "datetime_", "properties", "sortby", "q"}
    ),
    "pygeoapi.provider.tinydb_.TinyDBProvider": frozenset(
        {"bbox", "datetime_", "properties", "sortby", "q"}
    ),
    "app.provider.geoparquet.GeoParquetProvider": _FEATURE_ARGUMENTS | {"filterq"},
}
"""The arguments of ``query()`` each provider uses."""

ARGUMENT_PARAMETERS: dict[str, tuple[str, ...]] = {
    "bbox": ("bbox", "bbox-crs"),
    "datetime_": ("datetime",),
    "properties": (QUERYABLES,),
    "sortby": ("sortby",),
    "q": ("q",),
    "filterq": ("filter", "filter-lang", "filter-crs"),
    "select_properties": ("properties",),
    "skip_geometry": ("skipGeometry",),
    "crs_transform_spec": ("crs",),
}
"""The URL parameters pygeoapi turns into each argument of ``query()``."""

_FEATURES = "http://www.opengis.net/spec/ogcapi-features-"
_RECORDS = "http://www.opengis.net/spec/ogcapi-records-1/1.0/conf/"

CLASS_PARAMETERS: dict[str, tuple[str, ...]] = {
    f"{_FEATURES}1/1.0/conf/core": ("bbox", "datetime"),
    f"{_FEATURES}2/1.0/conf/crs": ("crs", "bbox-crs"),
    f"{_FEATURES}3/1.0/conf/queryables-query-parameters": (QUERYABLES,),
    f"{_FEATURES}3/1.0/conf/filter": ("filter", "filter-lang", "filter-crs"),
    f"{_FEATURES}3/1.0/conf/features-filter": ("filter", "filter-lang", "filter-crs"),
    f"{_RECORDS}core": ("bbox", "datetime", "q"),
    f"{_RECORDS}sorting": ("sortby",),
    f"{_RECORDS}opensearch": ("q",),
}
"""The parameters each conformance class brings, for providers that declare their classes."""

EXTENSIONS = frozenset({"properties", "skipGeometry"})
"""pygeoapi's own parameters, which no class names: a provider declaring its classes gets them."""


def _from_arguments(arguments: Iterable[str]) -> frozenset[str]:
    return ALWAYS | {parameter for each in arguments for parameter in ARGUMENT_PARAMETERS[each]}


def honoured(provider_def: dict[str, Any]) -> frozenset[str] | None:
    """The URL parameters the provider of ``provider_def`` applies; None when it does not say.

    A provider of pygeoapi or fastgeoapi is in the table, or descends from
    one that is. Any other counts through its ``conformance_classes``.
    """
    name = provider_def.get("name", "")
    dotted = PLUGINS["provider"].get(name, name)
    if dotted in PROVIDER_ARGUMENTS:
        return _from_arguments(PROVIDER_ARGUMENTS[dotted])
    cls = resolve_provider_class(dotted)
    for base in getattr(cls, "__mro__", ()):
        arguments = PROVIDER_ARGUMENTS.get(f"{base.__module__}.{base.__qualname__}")
        if arguments is not None:
            return _from_arguments(arguments)
    classes = getattr(cls, "conformance_classes", None)
    if not classes:
        return None
    return (
        ALWAYS
        | EXTENSIONS
        | {parameter for each in classes for parameter in CLASS_PARAMETERS.get(each, ())}
    )


@dataclass(frozen=True)
class Field:
    """One field of a page's form."""

    name: str
    label: str
    kind: str
    """``text``, ``number``, ``date``, ``select``, ``bbox`` or ``textarea``."""
    value: str = ""
    choices: tuple[tuple[str, str], ...] = ()
    """The value and the label of each choice of a ``select``, the empty one first."""
    hint: str = ""
    examples: tuple[str, ...] = ()


def _is_geometry(spec: dict[str, Any]) -> bool:
    return (
        spec.get("x-ogc-role") == "primary-geometry"
        or str(spec.get("format", "")).startswith("geometry")
        or "geojson" in str(spec.get("$ref", "")).lower()
    )


def _kind(spec: dict[str, Any]) -> str:
    if spec.get("enum"):
        return "select"
    if spec.get("type") in ("integer", "number"):
        return "number"
    if spec.get("format") == "date":
        return "date"
    return "text"


def queryable_fields(queryables: dict[str, Any], params: dict[str, str]) -> list[Field]:
    """A field for each queryable but the geometry, which the bbox stands for."""
    fields = []
    for name, spec in (queryables.get("properties") or {}).items():
        if _is_geometry(spec):
            continue
        kind = _kind(spec)
        choices = (
            (("", ""), *((str(value), str(value)) for value in spec["enum"]))
            if kind == "select"
            else ()
        )
        fields.append(Field(name, spec.get("title") or name, kind, params.get(name, ""), choices))
    return fields


def cql2_examples(fields: Iterable[Field]) -> tuple[str, ...]:
    """CQL2 text filters on the queryables, one for each kind of field the collection has."""
    examples: dict[str, str] = {}
    for field in fields:
        if field.kind == "text":
            examples.setdefault("text", f"{field.name} LIKE 'A%'")
        elif field.kind == "number":
            examples.setdefault("number", f"{field.name} > 0")
        elif field.kind == "select" and len(field.choices) > 1:
            examples.setdefault("select", f"{field.name} = '{field.choices[1][0]}'")
        elif field.kind == "date":
            examples.setdefault("date", f"{field.name} > DATE('2020-01-01')")
    return tuple(examples.values())


def items_fields(
    *,
    queryables: dict[str, Any],
    collection: dict[str, Any],
    params: dict[str, str],
    applied: frozenset[str] | None,
    gettext: Callable[[str], str],
) -> tuple[list[Field], list[Field]]:
    """The fields of the items form: the ones in view, then the advanced ones.

    A field shows when the collection's data applies its parameter, or
    when the provider does not say what it applies. ``datetime`` needs a
    temporal extent as well, and the reference systems need the
    collection's list.
    """
    _ = gettext

    def shown(name: str) -> bool:
        return applied is None or name in applied

    every = queryable_fields(queryables, params)
    systems = (("", ""), *((uri, uri) for uri in collection.get("crs") or []))
    temporal = ((collection.get("extent") or {}).get("temporal") or {}).get("interval")
    in_view = list(every) if shown(QUERYABLES) else []
    if shown("bbox"):
        in_view.append(
            Field(
                "bbox",
                _("Bounding box"),
                "bbox",
                params.get("bbox", ""),
                hint=_("West, south, east, north"),
            )
        )
    if shown("datetime") and temporal:
        in_view.append(
            Field(
                "datetime",
                _("Date and time"),
                "text",
                params.get("datetime", ""),
                hint=_("An instant, or an interval such as 2020-01-01/2020-12-31 or ../2020-12-31"),
            )
        )
    in_view.append(Field("limit", _("Items per page"), "number", params.get("limit", "")))
    advanced = []
    if shown("crs") and len(systems) > 1:
        advanced.append(
            Field("crs", _("Coordinate reference system"), "select", params.get("crs", ""), systems)
        )
    if shown("bbox-crs") and len(systems) > 1:
        advanced.append(
            Field(
                "bbox-crs",
                _("Reference system of the bounding box"),
                "select",
                params.get("bbox-crs", ""),
                systems,
            )
        )
    if shown("sortby") and every:
        orders = tuple(
            choice
            for field in every
            for choice in ((field.name, f"{field.name} ↑"), (f"-{field.name}", f"{field.name} ↓"))
        )
        advanced.append(
            Field("sortby", _("Sort by"), "select", params.get("sortby", ""), (("", ""), *orders))
        )
    if shown("properties"):
        advanced.append(
            Field(
                "properties",
                _("Properties to return"),
                "text",
                params.get("properties", ""),
                hint=_("Names separated by commas"),
            )
        )
    if shown("skipGeometry"):
        advanced.append(
            Field(
                "skipGeometry",
                _("Leave out the geometry"),
                "select",
                params.get("skipGeometry", ""),
                (("", _("No")), ("true", _("Yes"))),
            )
        )
    if shown("q"):
        advanced.append(Field("q", _("Search text"), "text", params.get("q", "")))
    if shown("filter"):
        advanced.append(
            Field(
                "filter",
                _("CQL2 filter"),
                "textarea",
                params.get("filter", ""),
                examples=cql2_examples(every),
            )
        )
        advanced.append(
            Field(
                "filter-lang",
                _("Filter language"),
                "select",
                params.get("filter-lang", ""),
                (("", ""), ("cql2-text", "CQL2 text"), ("cql2-json", "CQL2 JSON")),
            )
        )
        if len(systems) > 1:
            advanced.append(
                Field(
                    "filter-crs",
                    _("Reference system of the filter"),
                    "select",
                    params.get("filter-crs", ""),
                    systems,
                )
            )
    advanced.append(Field("offset", _("Start from item"), "number", params.get("offset", "")))
    advanced.append(
        Field(
            "resulttype",
            _("Result"),
            "select",
            params.get("resulttype", ""),
            (("", _("The items")), ("hits", _("Only how many they are"))),
        )
    )
    return in_view, advanced


@dataclass(frozen=True)
class Chip:
    """A parameter the page was asked with, and the link that drops it."""

    name: str
    value: str
    remove: str
    ignored: bool
    """The data does not apply it: pygeoapi passes it on and the provider leaves it."""


def chips(
    params: dict[str, str],
    url: str,
    applied: frozenset[str] | None,
    queryables: Iterable[str] | None,
) -> list[Chip]:
    """A chip for each parameter of the request but the language.

    A chip is marked ignored when the data does not apply its parameter, or
    when it names no queryable: pygeoapi drops those without a word.
    """
    known = None if queryables is None else set(queryables)
    found = []
    for name, value in params.items():
        if name == "lang":
            continue
        kind = name if name in ITEMS_PARAMETERS else QUERYABLES
        unknown = kind == QUERYABLES and known is not None and name not in known
        ignored = unknown or (applied is not None and kind not in applied)
        found.append(Chip(name, value, without_query(url, name), ignored))
    return found


_MESSAGES = (
    ("parameter-name", "parameter-name"),
    ("bbox-crs", "bbox-crs"),
    ("bbox", "bbox"),
    ("filter language", "filter-lang"),
    ("cql", "filter"),
    ("filter", "filter"),
    ("crs", "crs"),
    ("sortby", "sortby"),
    ("properties", "properties"),
    ("limit", "limit"),
    ("offset", "offset"),
    ("coords", "coords"),
    ("string", "datetime"),
    ("date", "datetime"),
)
"""Words of pygeoapi's 400 messages and the parameter each is about, the most specific first."""


def parameter_of(message: str, fields: Iterable[str]) -> str | None:
    """The field a message of pygeoapi is about, among the ``fields`` the page shows.

    None when the message names none of them: the page shows it above the
    form. A missing parameter (``missing coords parameter``) is about its
    field too, though the request does not have it.
    """
    lowered = message.lower()
    shown = set(fields)
    return next(
        (parameter for word, parameter in _MESSAGES if word in lowered and parameter in shown),
        None,
    )
