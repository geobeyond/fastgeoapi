"""The mapli map provider: configuration, parameters and styles, with a pool that draws nothing."""

import asyncio
import math
from http import HTTPStatus
from typing import Any
from unittest import mock

import pytest

from tests.maps_fixtures import tiny_png
from tests.mvt_fixtures import land_archive
from tests.pmtiles_fixtures import raster_archive, terrarium_archive

mapli = pytest.importorskip("mapli")

ROME = [1379000.0, 5140000.0, 1403000.0, 5160000.0]  # EPSG:3857 metres
WEB_MERCATOR = "http://www.opengis.net/def/crs/EPSG/0/3857"
BUCKET_DATA = "s3://bucket/tiles/land.pmtiles"


class FakeRenderPool:
    """Stands in for ``mapli.RenderPool``: records the styles and renders, draws flat PNGs."""

    instances: list["FakeRenderPool"] = []

    def __init__(self, workers: int = 1, max_renderers_per_worker: int = 8) -> None:
        self.workers = workers
        self.max_renderers_per_worker = max_renderers_per_worker
        self.styles: dict[str, Any] = {}
        self.renders: list[dict] = []
        self.fail: BaseException | None = None
        FakeRenderPool.instances.append(self)

    def has_style(self, style_id: str) -> bool:
        return style_id in self.styles

    def register_style(self, style_id, *, url=None, path=None, json=None) -> None:
        self.styles[style_id] = url if url is not None else json

    async def arender_from_bounds(self, style_id, *, bbox, width, height, **kwargs) -> bytes:
        if self.fail is not None:
            raise self.fail
        self.renders.append({"style_id": style_id, "bbox": tuple(bbox), "size": (width, height)})
        return tiny_png(width, height)

    def rendered_style(self, index: int = -1) -> Any:
        return self.styles[self.renders[index]["style_id"]]


@pytest.fixture(autouse=True)
def fake_pool(monkeypatch):
    FakeRenderPool.instances.clear()
    monkeypatch.setattr(mapli, "RenderPool", FakeRenderPool)
    yield
    FakeRenderPool.instances.clear()


@pytest.fixture
def archive(tmp_path):
    return land_archive(tmp_path / "land.pmtiles")


def _definition(data, options=None, **top_level) -> dict:
    return {
        "type": "map",
        "name": "app.provider.mapli.MapliMapProvider",
        "data": str(data),
        "storage_crs": WEB_MERCATOR,
        "options": options or {},
        "format": {"name": "png", "mimetype": "image/png"},
        **top_level,
    }


def _provider(data, options=None, **top_level):
    from app.provider.mapli import MapliMapProvider

    return MapliMapProvider(_definition(data, options, **top_level))


async def _map(provider, **kwargs):
    args = {"bbox": list(ROME), "width": 64, "height": 64, "crs": WEB_MERCATOR}
    return await provider.aquery(**{**args, **kwargs})


def _pool() -> FakeRenderPool:
    (pool,) = FakeRenderPool.instances
    return pool


def _background(style: dict) -> dict:
    (layer,) = [layer for layer in style["layers"] if layer["type"] == "background"]
    return layer


# Configuration


def test_building_a_provider_creates_no_render_pool(archive):
    _provider(archive)

    assert FakeRenderPool.instances == []


@pytest.mark.asyncio
async def test_the_first_map_creates_the_render_pool_and_the_next_ones_reuse_it(archive):
    provider = _provider(archive)
    await _map(provider)
    await _map(provider)

    assert len(_pool().renders) == 2


@pytest.mark.asyncio
async def test_the_defaults_suit_a_slim_node(archive):
    await _map(_provider(archive))

    assert (_pool().workers, _pool().max_renderers_per_worker) == (1, 4)


@pytest.mark.asyncio
async def test_the_pool_size_is_configurable(archive):
    await _map(_provider(archive, {"num_workers": 2, "max_renderers_per_worker": 3}))

    assert (_pool().workers, _pool().max_renderers_per_worker) == (2, 3)


def test_the_constructor_reads_nothing(tmp_path):
    _provider(tmp_path / "missing.pmtiles")


def test_another_storage_crs_is_refused(archive):
    from pygeoapi.provider.base import ProviderGenericError

    with pytest.raises(ProviderGenericError):
        _provider(archive, storage_crs="http://www.opengis.net/def/crs/OGC/1.3/CRS84")


def test_a_default_style_that_is_not_configured_is_refused(archive):
    from pygeoapi.provider.base import ProviderGenericError

    with pytest.raises(ProviderGenericError, match="not among the configured styles"):
        _provider(archive, {"default_style": "night"})


def test_an_unknown_dem_encoding_is_refused(tmp_path):
    from pygeoapi.provider.base import ProviderGenericError

    with pytest.raises(ProviderGenericError, match="dem must be one of"):
        _provider(raster_archive(tmp_path / "t.pmtiles"), {"dem": "srtm"})


def test_a_source_no_format_reads_is_refused(tmp_path):
    from pygeoapi.provider.base import ProviderGenericError

    with pytest.raises(ProviderGenericError, match="map source not supported"):
        _provider(tmp_path / "roads.geojson")


def test_a_bucket_needs_neither_the_range_cache_nor_a_data_url():
    _provider(BUCKET_DATA, {"range_cache": False})


# Bounding boxes


def test_the_world_in_web_mercator_is_the_world_in_crs84():
    from app.maps.camera import HALF_WORLD
    from app.provider.mapli import parse_web_mercator_bbox_as_crs84_bbox

    west, south, east, north = parse_web_mercator_bbox_as_crs84_bbox(
        [-HALF_WORLD, -HALF_WORLD, HALF_WORLD, HALF_WORLD]
    )

    assert (west, east) == pytest.approx((-180, 180))
    assert (south, north) == pytest.approx((-85.0511, 85.0511), abs=1e-4)


def test_the_world_stays_within_the_latitudes_mapli_draws():
    from app.maps.camera import HALF_WORLD
    from app.provider.mapli import MAX_LATITUDE, parse_web_mercator_bbox_as_crs84_bbox

    _, south, _, north = parse_web_mercator_bbox_as_crs84_bbox(
        [-HALF_WORLD, -HALF_WORLD, HALF_WORLD, HALF_WORLD]
    )

    assert -MAX_LATITUDE <= south < north <= MAX_LATITUDE


def test_a_bbox_beyond_the_poles_is_clamped():
    from app.maps.camera import HALF_WORLD
    from app.provider.mapli import parse_web_mercator_bbox_as_crs84_bbox

    _, south, _, north = parse_web_mercator_bbox_as_crs84_bbox(
        [0, -3 * HALF_WORLD, 1, 3 * HALF_WORLD]
    )

    assert (south, north) == pytest.approx((-85.0511, 85.0511), abs=1e-4)


def test_a_bbox_across_the_antimeridian_keeps_its_west_east_of_its_east():
    from app.maps.camera import HALF_WORLD
    from app.provider.mapli import parse_web_mercator_bbox_as_crs84_bbox

    west, _, east, _ = parse_web_mercator_bbox_as_crs84_bbox(
        [0.9 * HALF_WORLD, -1e6, -0.9 * HALF_WORLD, 1e6]
    )

    assert (west, east) == pytest.approx((162, -162))


# Parameters


@pytest.mark.asyncio
async def test_a_map_is_drawn_over_the_bbox_in_crs84(archive):
    png = await _map(_provider(archive))

    (render,) = _pool().renders
    west, south, east, north = render["bbox"]
    assert png.startswith(b"\x89PNG")
    assert render["size"] == (64, 64)
    assert 12.3 < west < east < 12.7
    assert 41.7 < south < north < 42.1


@pytest.mark.asyncio
async def test_a_map_without_bbox_is_the_world(archive):
    await _provider(archive).aquery(width=32, height=32)

    west, _, east, _ = _pool().renders[0]["bbox"]
    assert (west, east) == pytest.approx((-180, 180))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "parameters",
    [
        {"crs": "http://www.opengis.net/def/crs/OGC/1.3/CRS84"},
        {"format_": "jpeg"},
        {"width": 9},
        {"width": 2049},
        {"height": 9},
        {"height": 2049},
        {"bbox": [math.nan, 0, 1, 1]},
        {"style": "night"},
    ],
)
async def test_a_bad_parameter_answers_400(archive, parameters):
    from app.provider.maps import MapParameterError

    with pytest.raises(MapParameterError) as error:
        await _map(_provider(archive), **parameters)
    assert error.value.http_status_code == HTTPStatus.BAD_REQUEST
    assert all(pool.renders == [] for pool in FakeRenderPool.instances)


@pytest.mark.asyncio
async def test_max_size_bounds_the_width_and_height(archive):
    from app.provider.maps import MapParameterError

    provider = _provider(archive, {"max_size": 100})
    await _map(provider, width=100, height=100)

    with pytest.raises(MapParameterError):
        await _map(provider, width=101)


@pytest.mark.asyncio
async def test_web_mercator_is_recognised_whatever_the_case(archive):
    await _map(_provider(archive), crs=WEB_MERCATOR.lower())

    assert len(_pool().renders) == 1


@pytest.mark.asyncio
async def test_html_is_answered_with_the_image(archive):
    assert (await _map(_provider(archive), format_="html")).startswith(b"\x89PNG")


def test_the_sync_face_draws_with_the_arguments_it_is_given(archive):
    png = _provider(archive).query(bbox=list(ROME), width=40, height=20, crs=WEB_MERCATOR)

    assert png.startswith(b"\x89PNG")
    assert _pool().renders[0]["size"] == (40, 20)


# Styles


@pytest.mark.asyncio
async def test_the_default_style_draws_every_layer_of_the_archive(archive):
    await _map(_provider(archive))

    style = _pool().rendered_style()
    assert style["sources"] == {
        "dataset": {"type": "vector", "url": f"pmtiles://file://{archive.resolve()}"}
    }
    assert {layer["source-layer"] for layer in style["layers"] if "source" in layer} == {"land"}


@pytest.mark.asyncio
async def test_the_default_background_colour_is_configurable(archive):
    await _map(_provider(archive, {"default_background_color": "#ffff00"}), transparent=False)

    assert _background(_pool().rendered_style())["paint"]["background-color"] == "#ffff00"


@pytest.mark.asyncio
async def test_the_default_vector_colours_are_configurable(archive):
    await _map(_provider(archive, {"default_vector_colors": ["#123456"]}))

    fill = next(layer for layer in _pool().rendered_style()["layers"] if layer["type"] == "fill")
    assert fill["paint"]["fill-color"] == "#123456"


@pytest.mark.asyncio
async def test_the_default_hillshade_background_colour_is_configurable(tmp_path):
    archive = terrarium_archive(tmp_path / "t.pmtiles")
    options = {"dem": "terrarium", "default_hillshade_background_color": "#abcdef"}
    await _map(_provider(archive, options), transparent=False)

    assert _background(_pool().rendered_style())["paint"]["background-color"] == "#abcdef"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("transparent", "visibility"),
    [(True, "none"), ("true", "none"), ("TRUE", "none"), (False, "visible"), ("false", "visible")],
)
async def test_transparent_hides_the_background(archive, transparent, visibility):
    await _map(_provider(archive), transparent=transparent)

    assert _background(_pool().rendered_style())["layout"]["visibility"] == visibility


@pytest.mark.asyncio
async def test_transparent_and_opaque_maps_are_registered_apart(archive):
    provider = _provider(archive)
    await _map(provider, transparent=True)
    await _map(provider, transparent=False)
    await _map(provider, transparent=True)

    first, second, third = (render["style_id"] for render in _pool().renders)
    assert first != second
    assert first == third
    assert len(_pool().styles) == 2


@pytest.mark.asyncio
async def test_drawing_leaves_the_configured_style_as_it_was(archive):
    provider = _provider(archive)
    await _map(provider, transparent=True)
    await _map(provider, transparent=False)

    template = provider._map_styles["default"]
    assert "layout" not in _background(template)
    assert "url" not in template["sources"]["dataset"]


@pytest.mark.asyncio
async def test_a_named_style_is_drawn(archive):
    night = {"version": 8, "sources": {}, "layers": [{"id": "night", "type": "background"}]}
    await _map(_provider(archive, {"styles": {"night": night}}), style="night")

    assert [layer["id"] for layer in _pool().rendered_style()["layers"]] == ["night"]


@pytest.mark.asyncio
async def test_the_default_style_option_picks_the_style_drawn_without_one(archive):
    night = {"version": 8, "sources": {}, "layers": [{"id": "night", "type": "background"}]}
    await _map(_provider(archive, {"styles": {"night": night}, "default_style": "night"}))

    assert [layer["id"] for layer in _pool().rendered_style()["layers"]] == ["night"]


@pytest.mark.asyncio
async def test_a_style_naming_the_dataset_source_gets_the_url_of_the_data(archive):
    roads = {
        "version": 8,
        "sources": {"dataset": {"type": "vector"}},
        "layers": [{"id": "land", "type": "fill", "source": "dataset", "source-layer": "land"}],
    }
    await _map(_provider(archive, {"styles": {"roads": roads}}), style="roads")

    url = _pool().rendered_style()["sources"]["dataset"]["url"]
    assert url == f"pmtiles://file://{archive.resolve()}"


@pytest.mark.asyncio
async def test_a_style_given_as_a_url_is_registered_as_a_url(archive):
    styles = {"remote": "https://example.org/style.json"}
    await _map(_provider(archive, {"styles": styles}), style="remote")

    assert _pool().rendered_style() == "https://example.org/style.json"


@pytest.mark.asyncio
async def test_a_raster_archive_tells_its_tile_size(tmp_path):
    await _map(_provider(raster_archive(tmp_path / "r.pmtiles", size=256)))

    style = _pool().rendered_style()
    assert style["sources"]["dataset"]["type"] == "raster"
    assert style["sources"]["dataset"]["tileSize"] == 256
    assert style["layers"][-1]["type"] == "raster"


@pytest.mark.asyncio
async def test_an_elevation_archive_is_drawn_as_a_hillshade(tmp_path):
    await _map(_provider(terrarium_archive(tmp_path / "t.pmtiles"), {"dem": "terrarium"}))

    style = _pool().rendered_style()
    assert style["sources"]["dataset"]["type"] == "raster-dem"
    assert style["sources"]["dataset"]["encoding"] == "terrarium"
    assert style["layers"][-1]["type"] == "hillshade"


@pytest.mark.asyncio
async def test_the_styles_are_read_once(archive):
    provider = _provider(archive)
    await _map(provider)
    template = provider._map_styles["default"]
    await _map(provider)

    assert provider._map_styles["default"] is template


# Errors of mapli


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "message"),
    [
        (mapli.RenderError("boom"), "the map renderer failed"),
        (mapli.GraphicsUnavailableError("no GPU"), "the map renderer failed"),
        (mapli.StyleLoadError("bad json"), "style default could not be loaded"),
    ],
)
async def test_a_mapli_error_is_a_provider_error(archive, error, message):
    from pygeoapi.provider.base import ProviderGenericError

    provider = _provider(archive)
    await _map(provider)
    _pool().fail = error

    with pytest.raises(ProviderGenericError) as raised:
        await _map(provider)
    assert raised.value.message == message


# Data in a bucket, read through the mapli scheme handler


def _bucket_provider(tmp_path, origin=None):
    from app.provider.storage import CachedRanges
    from tests.range_cache_fixtures import CountingStore, memory_store, range_cache

    provider = _provider(BUCKET_DATA)
    origin = origin if origin is not None else CountingStore(memory_store())
    origin.put("land.pmtiles", land_archive(tmp_path / "land.pmtiles").read_bytes())
    provider.cached_ranges = CachedRanges(
        origin, "land.pmtiles", range_cache(memory_store()), source=BUCKET_DATA
    )
    return provider, origin


def _rendered_url() -> str:
    return _pool().rendered_style()["sources"]["dataset"]["url"].removeprefix("pmtiles://")


def _serve(url: str, data_range: tuple[int, int] | None = None):
    from app.provider.mapli import _SCHEME_HANDLER

    return _SCHEME_HANDLER(mapli.ResourceRequest(url=url, kind="source", data_range=data_range))


def _is_error(response, reason: str) -> bool:
    # mapli's Response exposes nothing but its repr, e.g. 'Response.error(NotFound, "...")'
    return repr(response).startswith(f"Response.error({reason},")


@pytest.mark.asyncio
async def test_a_bucket_is_read_through_the_scheme_handler(tmp_path):
    from app.provider.storage.cache import version_of

    provider, _ = _bucket_provider(tmp_path)
    await _map(provider)
    url = _rendered_url()
    cached = provider.cached_ranges

    assert url == f"fastgeoapi://{cached.source}/{version_of(cached.meta())}"
    assert bytes(_serve(url, (0, 6))) == b"PMTiles"


@pytest.mark.asyncio
async def test_a_range_past_the_end_is_clamped_and_one_beyond_it_is_not_found(tmp_path):
    provider, origin = _bucket_provider(tmp_path)
    await _map(provider)
    url, size = _rendered_url(), len(origin.get("land.pmtiles"))

    assert len(_serve(url, (size - 3, size + 100))) == 3
    assert len(_serve(url)) == size
    assert _is_error(_serve(url, (size, size + 10)), "NotFound")


@pytest.mark.asyncio
async def test_an_unknown_source_or_version_is_not_found(tmp_path):
    provider, _ = _bucket_provider(tmp_path)
    await _map(provider)
    source, version = _rendered_url().removeprefix("fastgeoapi://").split("/")

    assert _is_error(_serve(f"fastgeoapi://nope/{version}", (0, 6)), "NotFound")
    assert _is_error(_serve(f"fastgeoapi://{source}/nope", (0, 6)), "NotFound")


@pytest.mark.asyncio
async def test_data_that_changed_under_its_version_is_not_found(tmp_path):
    provider, origin = _bucket_provider(tmp_path)
    await _map(provider)
    url = _rendered_url()
    origin.put("land.pmtiles", origin.get("land.pmtiles") + b"\x00")

    assert _is_error(_serve(url, (0, 6)), "NotFound")


@pytest.mark.asyncio
async def test_a_failing_read_is_a_server_error(tmp_path):
    provider, _ = _bucket_provider(tmp_path)
    await _map(provider)
    url = _rendered_url()

    with mock.patch.object(provider.cached_ranges, "at", side_effect=OSError("boom")):
        assert _is_error(_serve(url, (0, 6)), "Server")


@pytest.mark.asyncio
async def test_a_new_version_of_the_data_is_drawn_with_a_new_style(tmp_path):
    provider, origin = _bucket_provider(tmp_path)
    await _map(provider)
    first_url, first_style = _rendered_url(), _pool().renders[-1]["style_id"]
    origin.put("land.pmtiles", origin.get("land.pmtiles") + b"\x00")
    provider.cached_ranges.invalidate()
    await _map(provider)
    second_url, second_style = _rendered_url(), _pool().renders[-1]["style_id"]

    assert first_url != second_url
    assert first_style != second_style


@pytest.mark.asyncio
async def test_the_first_map_of_a_bucket_blocks_nothing_on_the_loop(tmp_path):
    from tests.loop_guard import loop_guard

    provider, _ = _bucket_provider(tmp_path)
    with loop_guard():
        png = await _map(provider)

    assert png.startswith(b"\x89PNG")


# Data in a bucket without the range cache, read straight from its store


def _uncached_bucket_provider(tmp_path, options=None):
    from tests.range_cache_fixtures import CountingStore, memory_store

    provider = _provider(BUCKET_DATA, {"range_cache": False, **(options or {})})
    origin = CountingStore(memory_store())
    origin.put("land.pmtiles", land_archive(tmp_path / "land.pmtiles").read_bytes())
    provider.store = origin
    return provider, origin


@pytest.mark.asyncio
async def test_a_bucket_without_the_range_cache_is_read_from_its_store(tmp_path):
    from app.provider.storage.cache import digest, version_of

    provider, origin = _uncached_bucket_provider(tmp_path)
    await _map(provider)
    url = _rendered_url()
    reads_before = len(origin.range_reads)

    assert provider.cached_ranges is None
    assert url == f"fastgeoapi://{digest(BUCKET_DATA)}/{version_of(origin.head('land.pmtiles'))}"
    assert bytes(_serve(url, (0, 6))) == b"PMTiles"
    assert len(origin.range_reads) == reads_before + 1


@pytest.mark.asyncio
async def test_a_bucket_without_the_range_cache_is_looked_up_once(tmp_path):
    provider, origin = _uncached_bucket_provider(tmp_path)
    for _ in range(3):
        await _map(provider)

    assert origin.heads == 1


@pytest.mark.asyncio
async def test_a_bucket_with_a_data_url_and_no_range_cache_is_read_at_the_data_url(tmp_path):
    provider, origin = _uncached_bucket_provider(
        tmp_path, {"data_url": "https://example.org/land.pmtiles"}
    )
    await _map(provider)

    assert _rendered_url() == "https://example.org/land.pmtiles"
    assert origin.heads == 0


@pytest.mark.asyncio
async def test_concurrent_first_maps_share_one_pool_and_register_the_style_once(archive):
    provider = _provider(archive)
    await asyncio.gather(*(_map(provider) for _ in range(5)))

    assert len(_pool().renders) == 5
    assert len(_pool().styles) == 1


# The /map route


def _client(archive, options=None):
    from starlette.testclient import TestClient

    from app.pygeoapi.factory import build_openapi, build_pygeoapi_subapp
    from tests.test_tiles_async_route import _collection, _config

    config = _config({"land": _collection("Land", [_definition(archive, options)])})
    return TestClient(
        build_pygeoapi_subapp(config, build_openapi(config)), raise_server_exceptions=False
    )


def test_the_route_awaits_the_provider(archive):
    client = _client(archive)

    response = client.get(
        "/collections/land/map",
        params={"bbox": "12.4,41.8,12.6,42.0", "width": 64, "height": 48, "transparent": "false"},
    )

    assert response.status_code == 200, response.text[:200]
    assert response.headers["content-type"] == "image/png"
    assert _pool().renders[-1]["size"] == (64, 48)
    assert _background(_pool().rendered_style())["layout"]["visibility"] == "visible"


def test_the_route_draws_a_style_configured_under_options(archive):
    night = {"version": 8, "sources": {}, "layers": [{"id": "night", "type": "background"}]}
    client = _client(archive, {"styles": {"night": night}})

    response = client.get("/collections/land/styles/night/map", params={"width": 16, "height": 16})

    assert response.status_code == 200, response.text[:200]
    assert [layer["id"] for layer in _pool().rendered_style()["layers"]] == ["night"]


def test_the_route_answers_a_renderer_failure_in_json(archive):
    client = _client(archive)
    client.get("/collections/land/map", params={"width": 16, "height": 16})
    _pool().fail = mapli.RenderError("boom")

    response = client.get("/collections/land/map", params={"width": 16, "height": 16})

    assert response.status_code == 500
    assert response.json()["description"] == "the map renderer failed"
