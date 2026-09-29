"""The map provider: styles, limits and errors, with a renderer that draws nothing."""

import asyncio
import sys
from http import HTTPStatus
from unittest import mock

import pytest

from tests.maps_fixtures import FakeRenderer, map_provider
from tests.pmtiles_fixtures import TILE_BYTES, write_archive

ROME = (1379000.0, 5140000.0, 1403000.0, 5160000.0)  # EPSG:3857 metres
WEB_MERCATOR = "http://www.opengis.net/def/crs/EPSG/0/3857"


@pytest.fixture
def archive(tmp_path):
    return write_archive(
        tmp_path / "roads.pmtiles",
        {(0, 0, 0): TILE_BYTES(0, 0, 0)},
        metadata={"name": "roads", "vector_layers": [{"id": "roads"}]},
    )


@pytest.fixture(autouse=True)
def _fresh_fakes():
    FakeRenderer.instances.clear()
    FakeRenderer.gate = None
    yield
    FakeRenderer.instances.clear()


def _provider(archive, **options):
    from app.provider.maplibre import MapLibreMapProvider

    return MapLibreMapProvider(map_provider(archive, **options))


async def _map(provider, **kwargs):
    args = {"bbox": list(ROME), "width": 64, "height": 64, "crs": WEB_MERCATOR}
    return await provider.aquery(**{**args, **kwargs})


async def _until(condition, timeout=2.0):
    """Wait for a state of the provider instead of guessing how long it takes."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not condition():
        assert loop.time() < deadline, "the provider never reached the expected state"
        await asyncio.sleep(0.005)


@pytest.mark.asyncio
async def test_a_map_is_drawn_from_the_archive(archive):
    png = await _map(_provider(archive))

    (request,) = FakeRenderer.instances[0].requests
    assert png.startswith(b"\x89PNG")
    assert request.bbox == ROME
    assert (request.width, request.height) == (64, 64)
    assert request.style["sources"]["archive"]["url"] == f"pmtiles://file://{archive.resolve()}"


@pytest.mark.asyncio
async def test_the_constructor_reads_nothing(tmp_path):
    """pygeoapi builds the provider while writing the OpenAPI document."""
    _provider(tmp_path / "not-there.pmtiles")


@pytest.mark.asyncio
async def test_web_mercator_is_recognised_whatever_the_case(archive):
    """pygeoapi's get_uri lowercases a CRS URI before it reaches the provider."""
    png = await _map(_provider(archive), crs=WEB_MERCATOR.lower())

    assert png.startswith(b"\x89PNG")


@pytest.mark.asyncio
async def test_an_https_archive_is_read_as_it_is(tmp_path):
    from app.provider.maplibre import MapLibreMapProvider

    style = tmp_path / "plain.json"
    # The style declares its source, so the archive is never read.
    style.write_text('{"version": 8, "sources": {"archive": {"type": "vector"}}, "layers": []}')
    definition = map_provider(
        tmp_path / "unused.pmtiles", styles={"plain": str(style)}, default_style="plain"
    )
    definition["data"] = "https://example.org/tiles/roads.pmtiles"

    await _map(MapLibreMapProvider(definition))

    (request,) = FakeRenderer.instances[0].requests
    assert request.style["sources"]["archive"]["url"] == (
        "pmtiles://https://example.org/tiles/roads.pmtiles"
    )


def test_a_public_bucket_needs_the_data_url(tmp_path):
    from pygeoapi.provider.base import ProviderGenericError

    from app.provider.maplibre import MapLibreMapProvider

    definition = map_provider(tmp_path / "unused.pmtiles")
    definition["data"] = "s3://overturemaps-extras-us-west-2/tiles/places.pmtiles"
    definition["store_options"] = {"skip_signature": True}

    with pytest.raises(ProviderGenericError) as error:
        MapLibreMapProvider(definition)
    assert "data_url" in error.value.message


@pytest.mark.asyncio
async def test_the_data_url_is_what_the_renderer_reads(tmp_path):
    from app.provider.maplibre import MapLibreMapProvider

    style = tmp_path / "plain.json"
    # The style declares its source, so the archive is never read.
    style.write_text('{"version": 8, "sources": {"archive": {"type": "vector"}}, "layers": []}')
    public = "https://overturemaps.example/tiles/places.pmtiles"
    definition = map_provider(
        tmp_path / "unused.pmtiles",
        styles={"plain": str(style)},
        default_style="plain",
        data_url=public,
    )
    definition["data"] = "s3://overturemaps-extras-us-west-2/tiles/places.pmtiles"
    definition["store_options"] = {"skip_signature": True}

    await _map(MapLibreMapProvider(definition))

    (request,) = FakeRenderer.instances[0].requests
    assert request.style["sources"]["archive"]["url"] == f"pmtiles://{public}"


@pytest.mark.asyncio
async def test_style_source_names_the_collection_source_in_the_styles(archive):
    await _map(_provider(archive, style_source="roads"))

    (request,) = FakeRenderer.instances[0].requests
    assert request.style["sources"]["roads"]["url"] == f"pmtiles://file://{archive.resolve()}"
    assert "archive" not in request.style["sources"]


@pytest.mark.asyncio
async def test_a_signing_failure_is_a_provider_error(tmp_path):
    from unittest.mock import patch

    from pygeoapi.provider.base import ProviderGenericError

    from app.provider.maplibre import MapLibreMapProvider

    style = tmp_path / "plain.json"
    # The style declares its source, so the archive is never read.
    style.write_text('{"version": 8, "sources": {"archive": {"type": "vector"}}, "layers": []}')
    definition = map_provider(
        tmp_path / "unused.pmtiles", styles={"plain": str(style)}, default_style="plain"
    )
    definition["data"] = "s3://bucket/tiles/roads.pmtiles"
    provider = MapLibreMapProvider(definition)

    with patch.object(provider, "signed_url", side_effect=ValueError("cannot sign SECRET")):
        with pytest.raises(ProviderGenericError) as error:
            await _map(provider)
    assert "SECRET" not in error.value.message


def test_a_source_the_provider_cannot_read_is_refused(tmp_path):
    from pygeoapi.provider.base import ProviderGenericError

    from app.provider.maplibre import MapLibreMapProvider

    definition = map_provider(tmp_path / "roads.parquet")

    with pytest.raises(ProviderGenericError) as error:
        MapLibreMapProvider(definition)
    assert "map source not supported" in error.value.message


@pytest.mark.asyncio
async def test_a_registered_source_is_drawn_without_touching_the_provider(tmp_path):
    """A new map source is a class and its registration; the provider stays as it is."""
    from app.maps import sources, styles

    class GeoJSONSource:
        format = "geojson"

        def __init__(self, context):
            self._location = context.location()

        def url(self):
            return self._location.current()

        def content(self):
            from app.maps.contract import SourceContent

            return SourceContent("vector")

    data = tmp_path / "roads.geojson"
    data.write_text('{"type": "FeatureCollection", "features": []}')
    plain = tmp_path / "plain.json"
    plain.write_text(
        '{"version": 8, "sources": {}, "layers": [{"id": "r", "type": "line", "source": "archive"}]}'
    )
    translate = {"geojson": lambda url, content: {"type": "geojson", "data": url}}
    with mock.patch.dict(sources._REGISTRY), mock.patch.dict(styles._SOURCES, translate):
        sources.register_source(
            "geojson", matches=lambda data: data.endswith(".geojson"), build=GeoJSONSource
        )
        await _map(_provider(data, styles={"plain": str(plain)}, default_style="plain"))

    (request,) = FakeRenderer.instances[0].requests
    assert request.style["sources"]["archive"] == {
        "type": "geojson",
        "data": f"file://{data.resolve()}",
    }


@pytest.mark.asyncio
async def test_without_the_pmtiles_extra_a_map_says_what_to_install(archive, monkeypatch):
    from pygeoapi.provider.base import ProviderGenericError

    monkeypatch.setitem(sys.modules, "pmtiles", None)
    monkeypatch.setitem(sys.modules, "pmtiles.reader", None)

    with pytest.raises(ProviderGenericError) as error:
        await _map(_provider(archive))
    assert "pmtiles extra" in error.value.message


@pytest.mark.asyncio
async def test_an_avif_archive_is_refused_without_a_render(tmp_path):
    """MapLibre Native has no AVIF decoder: every render would fail and replace the renderer."""
    from pygeoapi.provider.base import ProviderGenericError

    from tests.pmtiles_fixtures import raster_archive

    archive = raster_archive(tmp_path / "hills.pmtiles", kind="AVIF")

    with pytest.raises(ProviderGenericError) as error:
        await _map(_provider(archive))
    assert "AVIF" in error.value.message
    assert FakeRenderer.instances == []


@pytest.mark.asyncio
async def test_a_broken_style_file_is_not_called_an_undrawable_source(archive, tmp_path):
    broken = tmp_path / "broken.json"
    broken.write_text("{not json")

    with pytest.raises(Exception) as error:
        await _map(_provider(archive, styles={"broken": str(broken)}), style="broken")
    assert "not drawable" not in str(error.value)


@pytest.mark.asyncio
async def test_the_style_factory_option_gives_the_styles_of_another_family(archive):
    await _map(_provider(archive, style_factory="tests.maps_fixtures.create_plain_styles"))

    (request,) = FakeRenderer.instances[0].requests
    assert request.style == {
        "url": f"file://{archive.resolve()}",
        "name": None,
        "transparent": True,
    }


@pytest.mark.asyncio
async def test_a_style_factory_that_cannot_be_loaded_says_so(archive):
    from pygeoapi.provider.base import ProviderGenericError

    with pytest.raises(ProviderGenericError) as error:
        await _map(_provider(archive, style_factory="tests.nowhere.create_styles"))
    assert "tests.nowhere.create_styles" in error.value.message
    assert FakeRenderer.instances == []


def test_the_default_styles_are_maplibre_styles():
    from app.provider.maplibre import DEFAULTS

    assert DEFAULTS["style_factory"] == "app.maps.styles.create_maplibre_styles"


@pytest.mark.asyncio
async def test_a_broken_style_leaves_the_other_styles_drawing(archive, tmp_path):
    from pygeoapi.provider.base import ProviderGenericError

    good = tmp_path / "good.json"
    good.write_text('{"version": 8, "sources": {}, "layers": [{"id": "g", "type": "background"}]}')
    broken = tmp_path / "broken.json"
    broken.write_text("{not json")
    provider = _provider(
        archive, styles={"good": str(good), "broken": str(broken)}, default_style="good"
    )

    assert (await _map(provider)).startswith(b"\x89PNG")
    with pytest.raises(ProviderGenericError) as error:
        await _map(provider, style="broken")
    assert "style broken could not be read" in error.value.message
    assert (await _map(provider, style="good")).startswith(b"\x89PNG")


def test_a_default_style_that_is_not_configured_is_refused(archive, tmp_path):
    from pygeoapi.provider.base import ProviderGenericError

    good = tmp_path / "good.json"
    good.write_text('{"version": 8, "sources": {}, "layers": []}')

    with pytest.raises(ProviderGenericError) as error:
        _provider(archive, styles={"good": str(good)}, default_style="nope")
    assert "default_style nope" in error.value.message


@pytest.mark.asyncio
async def test_another_crs_is_a_bad_parameter(archive):
    from app.provider.maps import MapParameterError

    with pytest.raises(MapParameterError) as error:
        await _map(_provider(archive), crs="http://www.opengis.net/def/crs/OGC/1.3/CRS84")
    assert error.value.http_status_code == HTTPStatus.BAD_REQUEST


@pytest.mark.asyncio
async def test_a_map_larger_than_max_size_answers_413(archive):
    from app.provider.maps import MapTooLargeError

    with pytest.raises(MapTooLargeError) as error:
        await _map(_provider(archive, max_size=1024), width=2000, height=64)
    assert error.value.http_status_code == HTTPStatus.REQUEST_ENTITY_TOO_LARGE


@pytest.mark.asyncio
async def test_a_size_below_one_is_a_bad_parameter(archive):
    from app.provider.maps import MapParameterError, MapTooLargeError

    with pytest.raises(MapParameterError) as error:
        await _map(_provider(archive), width=64, height=0)
    assert not isinstance(error.value, MapTooLargeError)
    assert error.value.http_status_code == HTTPStatus.BAD_REQUEST


@pytest.mark.asyncio
async def test_the_default_limit_fits_a_wide_browser_map(archive):
    """The collection page of pygeoapi asks for an image as wide as its map."""
    from app.provider.maps import MapTooLargeError

    png = await _map(_provider(archive), width=2048, height=400)

    assert png.startswith(b"\x89PNG")
    with pytest.raises(MapTooLargeError):
        await _map(_provider(archive), width=2049, height=400)


@pytest.mark.asyncio
async def test_another_format_is_a_bad_parameter(archive):
    from app.provider.maps import MapParameterError

    with pytest.raises(MapParameterError):
        await _map(_provider(archive), format_="jpeg")


@pytest.mark.asyncio
async def test_an_inverted_bbox_is_a_bad_parameter(archive):
    from app.provider.maps import MapParameterError

    # Only in latitude: a west edge east of the east edge crosses the antimeridian.
    with pytest.raises(MapParameterError):
        await _map(_provider(archive), bbox=[ROME[0], ROME[3], ROME[2], ROME[1]])


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [False, "false", "False", "0"])
async def test_transparent_false_keeps_the_background(archive, value):
    await _map(_provider(archive), transparent=value)

    (request,) = FakeRenderer.instances[0].requests
    assert request.style["layers"][0]["type"] == "background"
    assert request.transparent is False


@pytest.mark.asyncio
async def test_transparent_by_default_drops_the_background(archive):
    await _map(_provider(archive))

    (request,) = FakeRenderer.instances[0].requests
    assert all(layer["type"] != "background" for layer in request.style["layers"])


@pytest.mark.asyncio
async def test_an_unknown_style_is_not_found(archive):
    from pygeoapi.provider.base import ProviderItemNotFoundError

    with pytest.raises(ProviderItemNotFoundError):
        await _map(_provider(archive), style="missing")


@pytest.mark.asyncio
async def test_a_named_style_is_used(archive, tmp_path):
    style = tmp_path / "night.json"
    style.write_text('{"version": 8, "sources": {}, "layers": [{"id": "n", "type": "background"}]}')

    await _map(_provider(archive, styles={"night": str(style)}), style="night", transparent="false")

    (request,) = FakeRenderer.instances[0].requests
    assert request.style["layers"][0]["id"] == "n"


@pytest.mark.asyncio
async def test_a_full_queue_answers_503(archive):
    from app.provider.maps import MapRendererBusyError

    FakeRenderer.gate = asyncio.Event()
    provider = _provider(archive, fake="gate", queue=1)
    rendering = asyncio.create_task(_map(provider))
    waiting = asyncio.create_task(_map(provider))
    await _until(lambda: provider.waiting == 2)

    with pytest.raises(MapRendererBusyError) as error:
        await _map(provider)
    assert error.value.http_status_code == HTTPStatus.SERVICE_UNAVAILABLE

    FakeRenderer.gate.set()
    await asyncio.gather(rendering, waiting)


@pytest.mark.asyncio
async def test_a_slow_render_answers_504_and_keeps_drawing_for_the_cache(archive):
    from app.provider.maps import MapRenderTimeoutError

    FakeRenderer.gate = asyncio.Event()
    provider = _provider(archive, fake="gate", timeout=0.05, render_limit=5)
    with pytest.raises(MapRenderTimeoutError) as error:
        await _map(provider)
    assert error.value.http_status_code == HTTPStatus.GATEWAY_TIMEOUT

    # The render goes on, so the tiles it reads stay cached for the next maps.
    (renderer,) = FakeRenderer.instances
    assert not renderer.closed and provider.renderer_is_built
    FakeRenderer.gate.set()
    await _map(provider)
    assert FakeRenderer.instances == [renderer]
    assert renderer.calls == 2


@pytest.mark.asyncio
async def test_a_render_past_its_limit_replaces_the_renderer(archive):
    from app.provider.maps import MapRenderTimeoutError

    # Four times the timeout by default; the limit given here comes much sooner.
    provider = _provider(archive, fake="slow", timeout=1, render_limit=0.1)
    with pytest.raises(MapRenderTimeoutError):
        await _map(provider)

    await _until(lambda: FakeRenderer.instances[0].closed, timeout=0.5)
    assert provider.renderer_is_built is False


@pytest.mark.asyncio
async def test_a_map_waiting_behind_a_long_render_answers_504_in_time(archive):
    from app.provider.maps import MapRenderTimeoutError

    FakeRenderer.gate = asyncio.Event()
    provider = _provider(archive, fake="gate", timeout=0.05, render_limit=5)
    with pytest.raises(MapRenderTimeoutError):
        await _map(provider)

    loop = asyncio.get_running_loop()
    started = loop.time()
    with pytest.raises(MapRenderTimeoutError):
        await _map(provider)
    assert loop.time() - started < 1
    FakeRenderer.gate.set()


@pytest.mark.asyncio
async def test_a_crash_answers_500_and_the_next_map_gets_a_new_renderer(archive):
    from pygeoapi.provider.base import ProviderGenericError

    from app.provider.maps import MapRendererBusyError, MapRenderTimeoutError

    provider = _provider(archive, fake="crash-once")
    with pytest.raises(ProviderGenericError) as error:
        await _map(provider)
    assert not isinstance(error.value, (MapRendererBusyError, MapRenderTimeoutError))
    assert error.value.http_status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    png = await _map(provider)

    assert png.startswith(b"\x89PNG")
    assert len(FakeRenderer.instances) == 2
    assert FakeRenderer.instances[0].closed


@pytest.mark.asyncio
async def test_any_renderer_failure_replaces_it_and_keeps_its_message_private(archive):
    """A renderer may fail with anything; its message can carry a signed URL."""
    from pygeoapi.provider.base import ProviderGenericError

    provider = _provider(archive, fake="oserror-once")
    with pytest.raises(ProviderGenericError) as error:
        await _map(provider)
    assert "SECRET" not in error.value.message
    assert "SECRET" not in str(error.value)

    png = await _map(provider)

    assert png.startswith(b"\x89PNG")
    assert len(FakeRenderer.instances) == 2


@pytest.mark.asyncio
async def test_the_renderer_is_built_once(archive):
    provider = _provider(archive)
    await _map(provider)
    await _map(provider)

    assert len(FakeRenderer.instances) == 1


@pytest.mark.asyncio
async def test_a_missing_renderer_says_what_to_install(archive):
    from pygeoapi.provider.base import ProviderGenericError

    with pytest.raises(ProviderGenericError) as error:
        await _map(_provider(archive, renderer="app.maps.not_installed.create_renderer"))
    assert "maps dependency group" in error.value.message


@pytest.mark.asyncio
async def test_the_sync_face_hands_the_map_to_the_loop(archive):
    provider = _provider(archive)
    await _map(provider)

    png = await asyncio.to_thread(
        provider.query, bbox=list(ROME), width=32, height=32, crs=WEB_MERCATOR
    )

    assert png.startswith(b"\x89PNG")


@pytest.mark.asyncio
async def test_close_leaves_no_renderer_behind_the_queued_maps(archive):
    """A reload closes the provider while maps are still queued on it."""
    FakeRenderer.gate = asyncio.Event()
    provider = _provider(archive, fake="gate")
    rendering = asyncio.create_task(_map(provider))
    queued = asyncio.create_task(_map(provider))
    await _until(lambda: provider.waiting == 2)

    provider.close()
    FakeRenderer.gate.set()
    await asyncio.gather(rendering, queued)
    late = await _map(provider)  # the old sub-app may still serve one more map

    assert late.startswith(b"\x89PNG")
    await _until(lambda: all(renderer.closed for renderer in FakeRenderer.instances))
    assert provider.renderer_is_built is False


@pytest.mark.asyncio
async def test_close_waits_for_the_map_in_flight(archive):
    FakeRenderer.gate = asyncio.Event()
    provider = _provider(archive, fake="gate")
    rendering = asyncio.create_task(_map(provider))
    await _until(lambda: FakeRenderer.instances and FakeRenderer.instances[0].calls == 1)

    provider.close()
    await asyncio.sleep(0.01)
    assert not FakeRenderer.instances[0].closed

    FakeRenderer.gate.set()
    await rendering
    await _until(lambda: FakeRenderer.instances[0].closed)


@pytest.mark.asyncio
async def test_a_renderer_that_cannot_be_built_says_what_is_missing(archive):
    from pygeoapi.provider.base import ProviderGenericError

    provider = _provider(archive, renderer="tests.maps_fixtures.create_missing_renderer")

    with pytest.raises(ProviderGenericError) as error:
        await _map(provider)
    assert "maps dependency group" in error.value.message
    assert not provider.renderer_is_built


@pytest.mark.asyncio
async def test_aclose_waits_for_the_renderer_to_close(archive):
    provider = _provider(archive)
    await _map(provider)
    (renderer,) = FakeRenderer.instances

    await provider.aclose()

    assert renderer.closed and not provider.renderer_is_built


def test_the_map_errors_name_their_problem_in_the_log():
    from app.provider.maps import MapRendererBusyError, MapRenderTimeoutError

    assert str(MapRenderTimeoutError()) == "the map took too long to render"
    assert str(MapRendererBusyError()) == "the map renderer is busy, retry later"


@pytest.mark.asyncio
async def test_a_bbox_across_the_antimeridian_is_drawn(archive):
    from app.maps.camera import HALF_WORLD

    # West edge in the east, east edge in the west: the bbox crosses 180°.
    west, east = HALF_WORLD - 1_000_000.0, -HALF_WORLD + 1_000_000.0
    provider = _provider(archive)
    await _map(provider, bbox=[west, 5_140_000.0, east, 5_160_000.0])

    (request,) = FakeRenderer.instances[0].requests
    assert request.bbox[0] == west
    assert request.bbox[2] == pytest.approx(east + 2 * HALF_WORLD)


@pytest.mark.asyncio
async def test_html_is_answered_with_the_image(archive):
    """pygeoapi's map route serves the image when asked for HTML: there is no HTML map."""
    png = await _map(_provider(archive), format_="html")

    assert png.startswith(b"\x89PNG")
