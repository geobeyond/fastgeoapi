"""The item parameters: the ones each data source applies, the form, the chips, the messages.

``app.*`` is imported at the top of this module. Two tests read pygeoapi's
code: the catalog of the items route, and the arguments each provider's
``query()`` uses.
"""

import ast
import inspect
from pathlib import Path

import pygeoapi.api.itemtypes as itemtypes
import pygeoapi.provider as providers
import pytest

import app.provider.geoparquet as geoparquet
from app.html.parameters import (
    ALWAYS,
    ARGUMENT_PARAMETERS,
    ITEMS_PARAMETERS,
    PROVIDER_ARGUMENTS,
    QUERYABLES,
    Chip,
    chips,
    honoured,
    items_fields,
    parameter_of,
    queryable_fields,
)

GEOPARQUET = "app.provider.geoparquet.GeoParquetProvider"
FEATURES = "http://www.opengis.net/spec/ogcapi-features-"
CRS84 = "http://www.opengis.net/def/crs/OGC/1.3/CRS84"
WGS84 = "http://www.opengis.net/def/crs/EPSG/0/4326"
ITEMS = "http://example.org/geoapi/collections/lakes/items"

QUERYABLES_DOCUMENT = {
    "properties": {
        "geometry": {"format": "geometry-any", "x-ogc-role": "primary-geometry"},
        "name": {"title": "Name", "type": "string"},
        "area": {"type": "number"},
        "kind": {"type": "string", "enum": ["lake", "reservoir"]},
        "seen": {"type": "string", "format": "date"},
    }
}
COLLECTION = {
    "crs": [CRS84, WGS84],
    "extent": {"temporal": {"interval": [["2020-01-01T00:00:00Z", None]]}},
}


class LakesParquet(geoparquet.GeoParquetProvider):
    """A provider built on fastgeoapi's GeoParquet one."""


class Declared:
    """A provider of a third party that names its conformance classes."""

    conformance_classes = (
        f"{FEATURES}1/1.0/conf/core",
        f"{FEATURES}3/1.0/conf/features-filter",
    )


class Silent:
    """A provider of a third party that says nothing of what it applies."""


def _used(function: ast.FunctionDef) -> frozenset[str]:
    names = {argument.arg for argument in function.args.args}
    read = {node.id for node in ast.walk(function) if isinstance(node, ast.Name)}
    used = {name for name in ARGUMENT_PARAMETERS if name in names and name in read}
    # pygeoapi's @crs_transform reads crs_transform_spec and transforms what query() returns.
    decorators = {
        getattr(each, "id", getattr(each, "attr", "")) for each in function.decorator_list
    }
    if "crs_transform" in decorators:
        used.add("crs_transform_spec")
    return frozenset(used)


def _query(node: ast.ClassDef) -> ast.FunctionDef | None:
    return next(
        (each for each in node.body if isinstance(each, ast.FunctionDef) and each.name == "query"),
        None,
    )


def _scan() -> dict[str, frozenset[str]]:
    """The arguments the ``query()`` of each feature provider of pygeoapi reads, inherited too."""
    classes = {}
    for path in sorted(Path(providers.__file__).parent.glob("*.py")):
        for node in ast.parse(path.read_text()).body:
            if isinstance(node, ast.ClassDef):
                bases = [getattr(base, "id", getattr(base, "attr", "")) for base in node.bases]
                dotted = f"pygeoapi.provider.{path.stem}.{node.name}"
                classes[node.name] = (dotted, bases, _query(node))

    def query_of(name):
        _, bases, query = classes[name]
        inherited = (query_of(base) for base in bases if base in classes)
        return query if query is not None else next((each for each in inherited if each), None)

    found = {}
    for name, (dotted, _, _) in classes.items():
        query = query_of(name)
        if query is not None and "resulttype" in {argument.arg for argument in query.args.args}:
            found[dotted] = _used(query)
    return found


def test_the_catalog_is_the_one_of_the_items_route():
    tree = ast.parse(inspect.getsource(itemtypes.get_collection_items))
    reserved = next(
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(getattr(target, "id", None) == "reserved_fieldnames" for target in node.targets)
    )

    assert frozenset(ast.literal_eval(reserved)) == ITEMS_PARAMETERS


def test_the_table_of_providers_is_what_their_code_reads():
    ours = {name: used for name, used in PROVIDER_ARGUMENTS.items() if name.startswith("pygeoapi.")}

    assert ours == _scan()


def test_the_geoparquet_provider_reads_what_the_table_says():
    # From the file of the module imported above: ``inspect.getsource`` looks
    # the class up in ``sys.modules``, which a test that purges ``app.*`` empties.
    tree = ast.parse(Path(geoparquet.__file__).read_text())
    provider = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "GeoParquetProvider"
    )
    query = _query(provider)

    assert query is not None
    assert _used(query) == PROVIDER_ARGUMENTS[GEOPARQUET]


def test_a_provider_of_pygeoapi_applies_what_its_query_reads():
    assert honoured({"name": "GeoJSON"}) == ALWAYS | {
        "bbox",
        "bbox-crs",
        "crs",
        QUERYABLES,
        "properties",
        "skipGeometry",
    }


def test_a_subclass_applies_what_its_base_reads():
    applied = honoured({"name": "tests.test_html_parameters.LakesParquet"})

    assert applied is not None
    assert "filter" in applied


def test_a_provider_that_names_its_classes_applies_their_parameters():
    assert honoured({"name": "tests.test_html_parameters.Declared"}) == ALWAYS | {
        "bbox",
        "datetime",
        "filter",
        "filter-lang",
        "filter-crs",
        "properties",
        "skipGeometry",
    }


def test_a_provider_that_says_nothing_applies_everything():
    assert honoured({"name": "tests.test_html_parameters.Silent"}) is None


def test_each_queryable_but_the_geometry_is_a_field():
    fields = queryable_fields(QUERYABLES_DOCUMENT, {"name": "Garda"})

    assert [(field.name, field.label, field.kind, field.value) for field in fields] == [
        ("name", "Name", "text", "Garda"),
        ("area", "area", "number", ""),
        ("kind", "kind", "select", ""),
        ("seen", "seen", "date", ""),
    ]
    assert fields[2].choices == (("", ""), ("lake", "lake"), ("reservoir", "reservoir"))


def _names(fields):
    return [field.name for field in fields]


def test_the_form_shows_what_geojson_applies():
    in_view, advanced = items_fields(
        queryables=QUERYABLES_DOCUMENT,
        collection=COLLECTION,
        params={},
        applied=honoured({"name": "GeoJSON"}),
        gettext=str,
    )

    assert _names(in_view) == ["name", "area", "kind", "seen", "bbox", "limit"]
    assert _names(advanced) == [
        "crs",
        "bbox-crs",
        "properties",
        "skipGeometry",
        "offset",
        "resulttype",
    ]


def test_a_data_source_that_filters_gets_cql2_with_examples():
    in_view, advanced = items_fields(
        queryables=QUERYABLES_DOCUMENT,
        collection=COLLECTION,
        params={"filter": "area > 10"},
        applied=honoured({"name": GEOPARQUET}),
        gettext=str,
    )
    found = {field.name: field for field in advanced}

    assert _names(in_view) == ["name", "area", "kind", "seen", "bbox", "datetime", "limit"]
    assert _names(advanced) == [
        "bbox-crs",
        "sortby",
        "properties",
        "skipGeometry",
        "filter",
        "filter-lang",
        "filter-crs",
        "offset",
        "resulttype",
    ]
    assert (found["filter"].kind, found["filter"].value) == ("textarea", "area > 10")
    assert found["filter"].examples == (
        "name LIKE 'A%'",
        "area > 0",
        "kind = 'lake'",
        "seen > DATE('2020-01-01')",
    )
    assert found["sortby"].choices[1:3] == (("name", "name ↑"), ("-name", "name ↓"))


def test_without_queryables_nor_extents_the_form_is_the_bare_one():
    in_view, advanced = items_fields(
        queryables={}, collection={}, params={}, applied=None, gettext=str
    )

    assert _names(in_view) == ["bbox", "limit"]
    assert _names(advanced) == [
        "properties",
        "skipGeometry",
        "q",
        "filter",
        "filter-lang",
        "offset",
        "resulttype",
    ]


def test_every_parameter_is_a_chip_that_can_be_dropped():
    url = f"{ITEMS}?name=Garda&datetime=2020&nope=1&lang=it&f=html"
    params = {"name": "Garda", "datetime": "2020", "nope": "1", "lang": "it"}

    assert chips(params, url, honoured({"name": "GeoJSON"}), ["name"]) == [
        Chip("name", "Garda", f"{ITEMS}?datetime=2020&nope=1&lang=it&f=html", False),
        Chip("datetime", "2020", f"{ITEMS}?name=Garda&nope=1&lang=it&f=html", True),
        Chip("nope", "1", f"{ITEMS}?name=Garda&datetime=2020&lang=it&f=html", True),
    ]


def test_without_the_queryables_an_unknown_name_is_not_flagged():
    assert not chips({"nope": "1"}, "http://e.org/items?nope=1", None, None)[0].ignored


@pytest.mark.parametrize(
    ("message", "fields", "expected"),
    [
        ("bbox should be either 4 values (minx,miny,maxx,maxy) or 6 values", {"bbox"}, "bbox"),
        ("bbox-crs specified without bbox parameter", {"bbox-crs"}, "bbox-crs"),
        ("String does not contain a date: ", {"datetime"}, "datetime"),
        ("Unknown string format: nope", {"datetime"}, "datetime"),
        ("limit value should be an integer", {"limit"}, "limit"),
        ("offset value should be an integer", {"offset"}, "offset"),
        ("bad sortby property", {"sortby"}, "sortby"),
        ("unknown properties specified", {"properties"}, "properties"),
        ("Bad CQL text", {"filter"}, "filter"),
        ("Invalid filter language", {"filter-lang", "filter"}, "filter-lang"),
        ("CRS 'x' not supported for this collection.", {"crs"}, "crs"),
        ("missing coords parameter", {"coords", "z"}, "coords"),
        ("Invalid parameter-name", {"parameter-name", "coords"}, "parameter-name"),
        ("bbox should be either 4 values", {"limit"}, None),
    ],
)
def test_a_message_points_at_its_field(message, fields, expected):
    assert parameter_of(message, fields) == expected
