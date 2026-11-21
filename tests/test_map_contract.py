"""The contract a native map provider meets, and the configurations that break it.

``app.*`` is imported inside the tests, nowhere else. The two providers below
are loaded by their dotted path, as a configuration names them.
"""

import re
from typing import ClassVar

import pytest
from pygeoapi.provider.base import BaseProvider
from starlette.testclient import TestClient

from tests.maps_fixtures import map_provider, tiny_png
from tests.pmtiles_fixtures import TILE_BYTES, write_archive
from tests.test_tiles_async_route import _collection, _config

WEB_MERCATOR = "http://www.opengis.net/def/crs/EPSG/0/3857"
CRS84 = "http://www.opengis.net/def/crs/OGC/1.3/CRS84"


class NoVersion(BaseProvider):
    """A native map provider without ``aget_version``."""

    native_async = True

    async def arender_map(self, **kwargs):
        return b""

    @property
    def limits(self):
        return None

    def close(self):
        """Nothing to release."""


class Explicit(BaseProvider):
    """A native map provider that records the parameters passed by the route."""

    native_async = True
    received: ClassVar[list[dict]] = []

    async def arender_map(self, parameters):
        from app.interfaces.providers import RenderedMap

        Explicit.received.append(parameters)
        return RenderedMap(content=tiny_png(parameters.width, parameters.height), version=None)

    async def aget_version(self, parameters):
        return None

    @property
    def limits(self):
        from app.interfaces.providers import MapLimits

        return MapLimits(64, 64, None)

    @property
    def capabilities(self):
        from app.interfaces.providers import MapCapabilities

        return MapCapabilities(
            crs=(WEB_MERCATOR,), default_crs=WEB_MERCATOR, formats=("png",), styles=()
        )

    def close(self):
        """Nothing to release."""


def _build_capabilities_property(crs, formats, default_crs=None):
    """Build a ``capabilities`` property that declares ``crs``, ``formats`` and the default CRS."""

    @property
    def capabilities(self):
        from app.interfaces.providers import MapCapabilities

        return MapCapabilities(
            crs=crs, default_crs=default_crs or crs[0], formats=formats, styles=()
        )

    return capabilities


class UnknownFormat(Explicit):
    """A native map provider that draws a format outside the standard."""

    capabilities = _build_capabilities_property((WEB_MERCATOR,), ("gif",))


class CurieCrs(Explicit):
    """A native map provider that writes its CRS as a CURIE."""

    capabilities = _build_capabilities_property(("EPSG:3857",), ("png",))


class UnknownCrs(Explicit):
    """A native map provider that names a CRS no registry has."""

    capabilities = _build_capabilities_property(
        ("http://www.opengis.net/def/crs/EPSG/0/999999",), ("png",)
    )


class TwoFormats(Explicit):
    """A native map provider that draws PNG and JPEG and declares no classes."""

    capabilities = _build_capabilities_property((WEB_MERCATOR,), ("png", "jpeg"))


class DefaultOutsideCrs(Explicit):
    """A native map provider whose default CRS is not among those it draws."""

    capabilities = _build_capabilities_property((WEB_MERCATOR,), ("png",), CRS84)


class Crs84ByDefault(Explicit):
    """A native map provider that draws in CRS84 by default, whatever ``storage_crs`` says."""

    capabilities = _build_capabilities_property((WEB_MERCATOR, CRS84), ("png",), CRS84)


class MercatorByDefault(Explicit):
    """A native map provider that lists Web Mercator last and draws in it by default."""

    capabilities = _build_capabilities_property((CRS84, WEB_MERCATOR), ("png",), WEB_MERCATOR)


class Wider(Explicit):
    """A native map provider that draws larger maps than ``Explicit``."""

    @property
    def limits(self):
        from app.interfaces.providers import MapLimits

        return MapLimits(128, 128, None)


class NoCapabilities(BaseProvider):
    """A native map provider without ``capabilities``."""

    native_async = True

    async def arender_map(self, **kwargs):
        return b""

    async def aget_version(self, **kwargs):
        return None

    @property
    def limits(self):
        from app.interfaces.providers import MapLimits

        return MapLimits(64, 64, None)

    def close(self):
        """Nothing to release."""


class Threaded(BaseProvider):
    """A map provider pygeoapi calls in its threadpool."""

    def query(self, **kwargs):
        return b""


def _definition(name: str) -> dict:
    return {
        "type": "map",
        "name": name,
        "data": "unused",
        "storage_crs": WEB_MERCATOR,
        "format": {"name": "png", "mimetype": "image/png"},
    }


def _archive(tmp_path):
    return write_archive(
        tmp_path / "roads.pmtiles",
        {(0, 0, 0): TILE_BYTES(0, 0, 0)},
        metadata={"name": "roads", "vector_layers": [{"id": "roads"}]},
    )


def test_a_native_map_provider_without_aget_version_is_refused():
    from app.pygeoapi.factory import ConfigValidationError, normalize_config

    config = _config(
        {"lakes": _collection("Lakes", [_definition("tests.test_map_contract.NoVersion")])}
    )
    message = (
        "configuration at resources.lakes.providers.0: "
        "tests.test_map_contract.NoVersion sets native_async but has no aget_version"
    )

    with pytest.raises(ConfigValidationError, match=re.escape(message)):
        normalize_config(config)


@pytest.mark.parametrize(
    "member", ["arender_map", "aget_version", "limits", "capabilities", "close"]
)
def test_a_native_map_provider_without_a_member_of_the_contract_is_refused(member, monkeypatch):
    import sys

    from app.pygeoapi.factory import ConfigValidationError, normalize_config

    members = {k: v for k, v in vars(Explicit).items() if not k.startswith("__") and k != member}
    cls = type(f"Without_{member}", (BaseProvider,), members)
    monkeypatch.setattr(sys.modules[__name__], cls.__name__, cls, raising=False)
    name = f"{__name__}.{cls.__name__}"
    config = _config({"lakes": _collection("Lakes", [_definition(name)])})
    message = f"{name} sets native_async but has no {member}"

    with pytest.raises(ConfigValidationError, match=re.escape(message)):
        normalize_config(config)


def test_a_native_map_provider_without_capabilities_is_refused():
    from app.pygeoapi.factory import ConfigValidationError, normalize_config

    config = _config(
        {"lakes": _collection("Lakes", [_definition("tests.test_map_contract.NoCapabilities")])}
    )
    message = (
        "configuration at resources.lakes.providers.0: "
        "tests.test_map_contract.NoCapabilities sets native_async but has no capabilities"
    )

    with pytest.raises(ConfigValidationError, match=re.escape(message)):
        normalize_config(config)


def test_the_maplibre_capabilities_are_web_mercator_and_png(tmp_path):
    from app.interfaces.providers import MapCapabilities
    from app.provider.maplibre import MapLibreMapProvider

    provider = MapLibreMapProvider(map_provider(_archive(tmp_path)))

    assert provider.capabilities == MapCapabilities(
        crs=(WEB_MERCATOR,), default_crs=WEB_MERCATOR, formats=("png",), styles=()
    )


def test_the_maplibre_capabilities_name_the_configured_styles(tmp_path):
    from app.provider.maplibre import MapLibreMapProvider

    styles = {"night": "night.json", "day": "day.json"}
    provider = MapLibreMapProvider(map_provider(_archive(tmp_path), styles=styles))

    assert provider.capabilities.styles == ("day", "night")


def test_capabilities_name_the_styles_a_provider_draws():
    from app.interfaces.providers import MapCapabilities

    with pytest.raises(TypeError, match="styles"):
        MapCapabilities(crs=(WEB_MERCATOR,), default_crs=WEB_MERCATOR, formats=("png",))


def test_capabilities_name_the_default_crs():
    from app.interfaces.providers import MapCapabilities

    with pytest.raises(TypeError, match="default_crs"):
        MapCapabilities(crs=(WEB_MERCATOR,), formats=("png",), styles=())


def test_a_drawn_map_carries_its_image_and_version():
    from app.interfaces.providers import RenderedMap

    drawn = RenderedMap(content=b"png", version="v1")

    assert (drawn.content, drawn.version) == (b"png", "v1")
    with pytest.raises(AttributeError):
        drawn.version = "v2"  # ty: ignore[invalid-assignment]


def test_a_drawn_map_has_no_extra_headers_unless_the_provider_gives_them():
    from app.interfaces.providers import RenderedMap

    plain = RenderedMap(content=b"png", version="v1")
    tagged = RenderedMap(content=b"png", version="v1", extra_headers={"X-Engine": "fake"})

    assert dict(plain.extra_headers) == {}
    assert dict(tagged.extra_headers) == {"X-Engine": "fake"}


def test_map_parameters_carry_the_vendor_parameters():
    from app.interfaces.providers import MapParameters

    with pytest.raises(TypeError, match="vendor_params"):
        MapParameters(
            style=None,
            bbox=(0.0, 0.0, 1.0, 1.0),
            width=1,
            height=1,
            crs=WEB_MERCATOR,
            transparent=True,
            format_="png",
            datetime_=None,
            subsets=None,
        )


def test_a_map_not_drawn_carries_its_status_and_when_to_retry():
    from http import HTTPStatus

    from app.interfaces.providers import NotRenderedMap

    busy = NotRenderedMap(status=HTTPStatus.SERVICE_UNAVAILABLE, message="busy", retry_after=5)

    assert (busy.status, busy.message, busy.retry_after) == (503, "busy", 5)
    with pytest.raises(AttributeError):
        busy.retry_after = 1  # ty: ignore[invalid-assignment]


def test_the_maplibre_provider_meets_the_contract(tmp_path):
    import pygeoapi.plugin

    from app.interfaces.providers import AsyncMapProvider
    from app.pygeoapi.factory import normalize_config

    definition = map_provider(_archive(tmp_path))
    normalize_config(_config({"roads": _collection("Roads", [definition])}))

    assert isinstance(pygeoapi.plugin.load_plugin("provider", definition), AsyncMapProvider)


def test_the_route_passes_one_parameters_object():
    from app.interfaces.providers import MapParameters
    from app.pygeoapi.factory import (
        build_openapi,
        build_pygeoapi_subapp,
        normalize_config,
    )

    Explicit.received.clear()
    config = _config(
        {"lakes": _collection("Lakes", [_definition("tests.test_map_contract.Explicit")])}
    )
    normalize_config(config)
    app = build_pygeoapi_subapp(config, build_openapi(config))

    r = TestClient(app, raise_server_exceptions=False).get(
        "/collections/lakes/map",
        params={"bbox": "12.4,41.8,12.6,42.0", "width": 16, "height": 8},
    )

    assert r.status_code == 200
    (received,) = Explicit.received
    assert isinstance(received, MapParameters)
    assert (received.width, received.height, received.crs) == (
        16,
        8,
        WEB_MERCATOR,
    )
    assert isinstance(received.bbox, tuple)
    assert len(received.bbox) == 4


def test_a_map_provider_that_is_not_native_is_left_to_pygeoapi():
    from app.pygeoapi.api_async.maps import find_native_map_provider
    from app.pygeoapi.factory import build_api, build_openapi, normalize_config

    config = _config(
        {"lakes": _collection("Lakes", [_definition("tests.test_map_contract.Threaded")])}
    )
    normalize_config(config)

    assert find_native_map_provider(build_api(config, build_openapi(config)), "lakes") is None


def test_the_maplibre_limits_come_from_its_options(tmp_path):
    from app.interfaces.providers import MapLimits
    from app.provider.maplibre import MapLibreMapProvider

    provider = MapLibreMapProvider(
        map_provider(_archive(tmp_path), max_size=1024, queue=3, timeout=12)
    )

    assert provider.limits == MapLimits(1024, 1024, None)


def test_the_map_family_protocol_is_exported():
    import app.interfaces
    import app.interfaces.providers

    assert app.interfaces.AsyncMapProvider is app.interfaces.providers.AsyncMapProvider


MAPS = "http://www.opengis.net/spec/ogcapi-maps-1/1.0/conf"


def test_the_map_formats_are_the_encodings_of_the_standard():
    from app.interfaces.providers import MapFormat

    assert {member.value for member in MapFormat} == {
        "png",
        "jpeg",
        "jpegxl",
        "tiff",
        "svg",
        "html",
    }
    assert MapFormat("png").media_type == "image/png"
    assert MapFormat("jpeg").conformance_class == f"{MAPS}/jpeg"


@pytest.mark.parametrize(
    ("format_", "media_type"),
    [
        ("png", "image/png"),
        ("jpeg", "image/jpeg"),
        ("jpegxl", "image/jxl"),
        ("tiff", "image/tiff"),
        ("svg", "image/svg+xml"),
        ("html", "text/html"),
    ],
)
def test_each_map_format_has_its_media_type(format_, media_type):
    from app.interfaces.providers import MapFormat

    assert MapFormat(format_).media_type == media_type


@pytest.mark.parametrize(
    ("provider", "message"),
    [
        ("UnknownFormat", "draws gif, which is not a format of OGC API - Maps"),
        ("CurieCrs", "names the CRS EPSG:3857, which is not an OGC CRS URI"),
        (
            "UnknownCrs",
            "names the CRS http://www.opengis.net/def/crs/EPSG/0/999999, which is not an OGC CRS URI",
        ),
        (
            "DefaultOutsideCrs",
            f"draws by default in {CRS84}, which is not among its CRSs",
        ),
    ],
)
def test_a_native_map_provider_with_capabilities_outside_the_standard_is_refused(provider, message):
    from app.pygeoapi.factory import ConfigValidationError, normalize_config

    name = f"tests.test_map_contract.{provider}"
    config = _config({"lakes": _collection("Lakes", [_definition(name)])})

    with pytest.raises(
        ConfigValidationError,
        match=re.escape(f"configuration at resources.lakes.providers.0: {name} {message}"),
    ):
        normalize_config(config)


@pytest.mark.parametrize("provider", ["NoVersion", "NoCapabilities", "UnknownFormat", "CurieCrs"])
def test_the_editor_refuses_the_map_providers_the_start_refuses(provider):
    import copy

    import yaml

    from app.editor.inspect import validation_problems
    from app.pygeoapi.factory import ConfigValidationError, normalize_config

    name = f"tests.test_map_contract.{provider}"
    config = _config({"lakes": _collection("Lakes", [_definition(name)])})
    with pytest.raises(ConfigValidationError) as refused:
        normalize_config(copy.deepcopy(config))

    problems = validation_problems(yaml.safe_dump(config))

    assert problems == [str(refused.value).removeprefix("invalid fastgeoapi configuration at ")]


def test_the_conformance_classes_come_from_the_capabilities():
    from app.pygeoapi.factory import build_openapi, build_pygeoapi_subapp

    config = _config(
        {"lakes": _collection("Lakes", [_definition("tests.test_map_contract.TwoFormats")])}
    )
    declared = set(
        TestClient(build_pygeoapi_subapp(config, build_openapi(config)))
        .get("/conformance", params={"f": "json"})
        .json()["conformsTo"]
    )

    assert {
        f"{MAPS}/core",
        f"{MAPS}/collection-map",
        f"{MAPS}/png",
        f"{MAPS}/jpeg",
    } <= declared
    assert f"{MAPS}/tiff" not in declared


def _serve(collection: dict) -> TestClient:
    from app.pygeoapi.factory import (
        build_openapi,
        build_pygeoapi_subapp,
        normalize_config,
    )

    config = _config({"lakes": collection})
    normalize_config(config)
    return TestClient(build_pygeoapi_subapp(config, build_openapi(config)))


@pytest.mark.parametrize(
    ("asked", "media_type", "drawn"),
    [
        ("jpeg", "image/jpeg", "jpeg"),
        ("png", "image/png", "png"),
        ("html", "image/png", "png"),
    ],
)
def test_a_map_carries_the_type_of_the_format_it_was_drawn_in(asked, media_type, drawn):
    Explicit.received.clear()
    client = _serve(_collection("Lakes", [_definition("tests.test_map_contract.TwoFormats")]))

    r = client.get(
        "/collections/lakes/map",
        params={
            "bbox": "12.4,41.8,12.6,42.0",
            "width": 16,
            "height": 8,
            "f": asked,
        },
    )

    assert r.status_code == 200
    assert r.headers["content-type"] == media_type
    assert Explicit.received[-1].format_ == drawn


def test_the_map_responses_list_every_format_drawn():
    from app.pygeoapi.factory import build_openapi

    config = _config(
        {"lakes": _collection("Lakes", [_definition("tests.test_map_contract.TwoFormats")])}
    )
    document = build_openapi(config)
    content = document["paths"]["/collections/lakes/map"]["get"]["responses"]["200"]["content"]

    assert set(content) == {"image/png", "image/jpeg"}


def test_the_published_limits_are_those_of_the_provider_the_route_serves():
    from app.pygeoapi.factory import build_openapi

    first = _definition("tests.test_map_contract.Explicit")
    second = _definition("tests.test_map_contract.Wider")
    document = build_openapi(_config({"lakes": _collection("Lakes", [first, second])}))
    parameters = document["paths"]["/collections/lakes/map"]["get"]["parameters"]
    width = next(p for p in parameters if p.get("name") == "width")

    assert width["schema"]["maximum"] == 64


def test_the_collection_describes_the_crss_of_its_map():
    client = _serve(_collection("Lakes", [_definition("tests.test_map_contract.TwoFormats")]))

    collection = client.get("/collections/lakes", params={"f": "json"}).json()

    assert WEB_MERCATOR in collection["crs"]
    assert collection["storageCrs"] == WEB_MERCATOR
    (bbox,) = collection["extent"]["spatial"]["storageCrsBbox"]
    assert len(bbox) == 4
    assert all(abs(value) <= 20037508.35 for value in bbox)


def test_the_collection_links_a_map_per_format():
    client = _serve(_collection("Lakes", [_definition("tests.test_map_contract.TwoFormats")]))

    collection = client.get("/collections/lakes", params={"f": "json"}).json()
    maps = [link for link in collection["links"] if link["rel"].endswith("/ogc/1.0/map")]

    assert {link["type"] for link in maps} == {"image/png", "image/jpeg"}
    assert {link["href"].rsplit("f=", 1)[-1] for link in maps} == {
        "png",
        "jpeg",
    }


def test_a_safe_curie_names_the_map_crs():
    client = _serve(_collection("Lakes", [_definition("tests.test_map_contract.TwoFormats")]))

    r = client.get(
        "/collections/lakes/map",
        params={
            "bbox": "12.4,41.8,12.6,42.0",
            "width": 16,
            "height": 8,
            "crs": "[EPSG:3857]",
        },
    )

    assert r.status_code == 200
    assert WEB_MERCATOR in r.headers["content-crs"]


def test_the_crs_class_is_declared_once_the_collection_lists_the_crss():
    declared = set(
        _serve(_collection("Lakes", [_definition("tests.test_map_contract.TwoFormats")]))
        .get("/conformance", params={"f": "json"})
        .json()["conformsTo"]
    )

    assert f"{MAPS}/crs" in declared


def test_a_map_without_crs_is_drawn_in_the_default_crs_of_the_provider():
    client = _serve(_collection("Lakes", [_definition("tests.test_map_contract.Crs84ByDefault")]))
    Explicit.received.clear()

    r = client.get("/collections/lakes/map", params={"width": 16, "height": 8})

    assert r.status_code == 200, r.text[:200]
    assert Explicit.received[-1].crs == CRS84
    assert r.headers["content-crs"] == CRS84


def test_the_crs_parameter_publishes_the_default_crs_of_the_provider():
    from app.pygeoapi.factory import build_openapi

    name = "tests.test_map_contract.Crs84ByDefault"
    document = build_openapi(_config({"lakes": _collection("Lakes", [_definition(name)])}))
    parameters = document["paths"]["/collections/lakes/map"]["get"]["parameters"]
    crs = next(p for p in parameters if p.get("name") == "crs")

    assert crs["schema"]["default"] == CRS84


def test_the_collection_lists_the_default_crs_first_as_its_storage_crs():
    name = "tests.test_map_contract.MercatorByDefault"
    collection = _serve(_collection("Lakes", [_definition(name)])).get(
        "/collections/lakes", params={"f": "json"}
    )

    described = collection.json()
    assert described["crs"][0] == WEB_MERCATOR
    assert described["storageCrs"] == WEB_MERCATOR


def test_a_collection_drawn_in_crs84_by_default_has_no_storage_crs():
    name = "tests.test_map_contract.Crs84ByDefault"
    described = (
        _serve(_collection("Lakes", [_definition(name)]))
        .get("/collections/lakes", params={"f": "json"})
        .json()
    )

    assert described["crs"][0] == CRS84
    assert "storageCrs" not in described
