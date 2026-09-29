"""The parts every OGC API Maps provider composes, as functions and errors.

A map provider is one line of classes, like every provider here: the
async mixin and pygeoapi's root. From this module it takes what it shares
with the other map providers: the checks of its definition, the URL of
its data, its style documents, its renderer, the
:class:`~app.maps.contract.MapRequest` of the OGC API Maps parameters,
and the errors pygeoapi turns into HTTP answers. It adds a
:class:`~app.maps.queue.RenderQueue` and the styles of its family. Maps
are drawn in EPSG:3857, the CRS of the contract's request.
"""

from __future__ import annotations

import importlib
import json
import math
from collections.abc import Callable, Iterator, Mapping
from datetime import timedelta
from http import HTTPStatus
from pathlib import Path
from typing import Any

from pygeoapi.provider.base import ProviderGenericError, ProviderItemNotFoundError

from app.config.logging import create_logger
from app.maps.camera import HALF_WORLD
from app.maps.contract import (
    MapRenderer,
    MapRequest,
    MapSource,
    MapStyles,
    RenderError,
    SourceNotDrawableError,
)
from app.maps.queue import DrawTimeoutError, QueueFullError, RenderQueue
from app.maps.sources import ObjectUrl, SourceFormat, source_for
from app.provider.storage import cache as range_caches
from app.provider.storage import load_store, split_source

logger = create_logger("app.provider.maps")

WEB_MERCATOR = "http://www.opengis.net/def/crs/EPSG/0/3857"
"""The only CRS maps are drawn in."""

_MAPS = "http://www.opengis.net/spec/ogcapi-maps-1/1.0/conf"

MAPS_CONFORMANCE: tuple[str, ...] = (
    f"{_MAPS}/core",
    f"{_MAPS}/collection-map",
    f"{_MAPS}/png",
    f"{_MAPS}/scaling",
    f"{_MAPS}/spatial-subsetting",
    f"{_MAPS}/background",
)
"""The OGC API Maps classes a provider built from these parts passes."""


class _MapError(ProviderGenericError):
    """A map error whose message, when none is given, is its ``default_msg``.

    pygeoapi's errors pass ``msg`` on to the exception, so one raised
    without a message logs as ``None``.
    """

    def __init__(self, msg: str | None = None, *args: Any, user_msg: str | None = None) -> None:
        super().__init__(msg or user_msg or self.default_msg, *args, user_msg=user_msg)


class MapParameterError(_MapError):
    """A map parameter this server cannot honour."""

    ogc_exception_code = "InvalidParameterValue"
    http_status_code = HTTPStatus.BAD_REQUEST
    default_msg = "invalid map parameter"


class MapTooLargeError(MapParameterError):
    """A width or height above ``max_size``: OGC API - Maps prefers a 413 for it."""

    http_status_code = HTTPStatus.REQUEST_ENTITY_TOO_LARGE
    default_msg = "the map is larger than this server draws"


class MapRendererBusyError(_MapError):
    """Too many maps are already waiting for the renderer."""

    http_status_code = HTTPStatus.SERVICE_UNAVAILABLE
    default_msg = "the map renderer is busy, retry later"
    # Seconds for the Retry-After header: a warm map takes well under one, the
    # first map of a small area from 2 to 9.
    retry_after = 5


class MapRenderTimeoutError(_MapError):
    """The renderer took longer than the configured timeout."""

    http_status_code = HTTPStatus.GATEWAY_TIMEOUT
    default_msg = "the map took too long to render"


def is_bucket(data: str) -> bool:
    """Whether ``data`` is a bucket key, neither a local path nor an http URL."""
    return "://" in data and not data.startswith(("file://", "http://", "https://"))


def reads_through_range_cache(options: dict[str, Any]) -> bool:
    """Whether the renderer reads remote data through the range cache of this process."""
    return bool(options.get("range_cache", True)) and range_caches.range_cache_enabled()


def check_definition(provider_def: dict, options: dict[str, Any]) -> SourceFormat:
    """The source format of a map provider's data, once its definition holds together.

    Raises :class:`ProviderGenericError` for a storage CRS other than
    EPSG:3857, for data that no registered source reads, for a
    ``default_style`` that is not configured, and for a public bucket
    without ``data_url`` when the range cache is off.
    """
    storage_crs = provider_def.get("storage_crs", WEB_MERCATOR)
    if storage_crs != WEB_MERCATOR:
        raise ProviderGenericError(
            user_msg=f"the map provider draws in {WEB_MERCATOR}, not in {storage_crs}"
        )
    try:
        source_format = source_for(provider_def["data"])
    except LookupError as error:
        raise ProviderGenericError(user_msg=f"map source not supported: {error}") from None
    default = options.get("default_style")
    if default is not None and default not in (options.get("styles") or {}):
        raise ProviderGenericError(
            user_msg=f"default_style {default} is not among the configured styles"
        )
    store_options = provider_def.get("store_options") or {}
    # Without the range cache the renderer fetches the data with plain HTTP:
    # a public bucket read without signatures has no URL to sign, and obstore
    # would first spend seconds looking for credentials.
    if store_options.get("skip_signature") and not options.get("data_url"):
        if is_bucket(provider_def["data"]) and not reads_through_range_cache(options):
            raise ProviderGenericError(
                user_msg="a public bucket needs options.data_url, the https URL of the data"
            )
    return source_format


def object_url(
    data: str, *, public_url: str | None, sign: Callable[[timedelta], str], ttl: timedelta
) -> ObjectUrl:
    """The URL of the data object for a renderer: public, local, or signed by ``sign``."""
    if public_url:
        return ObjectUrl(public_url=public_url)
    if data.startswith(("http://", "https://")):
        return ObjectUrl(public_url=data)
    if not is_bucket(data):
        return ObjectUrl(local_path=Path(data.removeprefix("file://")))

    def signer(expires_in: timedelta) -> str:
        try:
            return sign(expires_in)
        except Exception as error:
            logger.warning(f"could not sign the data URL: {type(error).__name__}")
            raise ProviderGenericError(user_msg="the data URL could not be signed") from None

    return ObjectUrl(signer=signer, ttl=ttl)


def read_style(location: str, store_options: dict | None) -> dict:
    """A style document from a local path or a bucket."""
    if "://" not in location:
        return json.loads(Path(location).read_text())
    base, key = split_source(location)
    return json.loads(load_store(base, store_options).get(key))


class StyleDocuments(Mapping[str, dict]):
    """The configured style documents, each read at its first use.

    A style that cannot be read fails alone, with an error pygeoapi answers
    in JSON; the other styles keep drawing, and a failed read is tried
    again at the next map.
    """

    def __init__(self, locations: Mapping[str, str], store_options: dict | None) -> None:
        """``locations`` maps each style name to its path or bucket key."""
        self._locations = dict(locations)
        self._store_options = store_options
        self._read: dict[str, dict] = {}

    def __getitem__(self, name: str) -> dict:
        """The document of style ``name``; :class:`KeyError` when it is not configured."""
        if name not in self._read:
            location = self._locations[name]
            try:
                self._read[name] = read_style(location, self._store_options)
            except Exception as error:
                logger.warning(f"could not read style {name}: {type(error).__name__}")
                raise ProviderGenericError(user_msg=f"style {name} could not be read") from None
        return self._read[name]

    def __iter__(self) -> Iterator[str]:
        """The configured style names."""
        return iter(self._locations)

    def __len__(self) -> int:
        """How many styles are configured."""
        return len(self._locations)


def render_limit(options: dict[str, Any]) -> float:
    """Seconds a render may go on after its map answered 504: four times the timeout by default."""
    limit = options.get("render_limit")
    return float(limit) if limit is not None else 4 * float(options["timeout"])


def load_factory(
    options: dict[str, Any], option: str, *, unavailable: str, hint: str = ""
) -> Callable[..., Any]:
    """The function the dotted path in ``options[option]`` names.

    When it cannot be loaded, the error message starts with ``unavailable``.
    """
    dotted = options.get(option)
    if not dotted:
        raise ProviderGenericError(user_msg=f"{unavailable}: options.{option} names nothing")
    module_name, _, name = dotted.rpartition(".")
    try:
        return getattr(importlib.import_module(module_name), name)
    except (ImportError, AttributeError) as error:
        raise ProviderGenericError(
            user_msg=f"{unavailable}: {dotted} could not be loaded{hint}"
        ) from error


def build_renderer(options: dict[str, Any]) -> MapRenderer:
    """The renderer the ``renderer`` option names, built from the options."""
    factory = load_factory(
        options,
        "renderer",
        unavailable="map rendering is not available",
        hint="; install the maps dependency group",
    )
    try:
        return factory({**options, "render_limit": render_limit(options)})
    except ImportError as error:
        raise ProviderGenericError(user_msg=f"map rendering is not available: {error}") from error


def build_styles(
    source: MapSource, documents: Mapping[str, dict], options: dict[str, Any]
) -> MapStyles:
    """The styles the ``style_factory`` option names, over ``source``.

    Styles and renderer go together: the factory must give styles in the
    language the renderer reads.
    """
    factory = load_factory(options, "style_factory", unavailable="map styles are not available")
    return factory(source, documents, options)


def _flag(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in ("false", "0", "no")
    return bool(value)


def _clamp(value: float) -> float:
    if math.isnan(value):
        return value
    return max(-HALF_WORLD, min(HALF_WORLD, value))


def map_request(
    style_for: Callable[[str | None, bool], Any],
    *,
    max_size: int,
    style: str | None = None,
    bbox: list[float] | None = None,
    width: int = 500,
    height: int = 300,
    crs: str | None = None,
    transparent: Any = True,
    format_: str | None = "png",
) -> MapRequest:
    """The map to draw for the OGC API Maps parameters of one request.

    ``style_for(name, transparent)`` resolves the style of the family.
    Raises the errors of this module, and pygeoapi's not-found error for
    a style that is not configured.
    """
    # pygeoapi's get_uri lowercases a CRS URI on its way here.
    if crs is not None and crs.lower() != WEB_MERCATOR.lower():
        raise MapParameterError(user_msg=f"maps are drawn in {WEB_MERCATOR} only")
    # pygeoapi's map route answers f=html with the image itself, as there is no
    # HTML map page: a PNG is drawn for it too.
    if format_ not in (None, "png", "html"):
        raise MapParameterError(user_msg="maps are drawn as PNG only")
    if int(width) < 1 or int(height) < 1:
        raise MapParameterError(user_msg="width and height must be at least 1")
    if int(width) > max_size or int(height) > max_size:
        raise MapTooLargeError(user_msg=f"width and height must be at most {max_size}")
    transparent = _flag(transparent)
    try:
        chosen = style_for(style, transparent)
    except KeyError as error:
        raise ProviderItemNotFoundError(user_msg=f"style {style} not found") from error
    except ImportError as error:
        # A source imports the library of its format at its first read, and
        # the library may come from an extra that is not installed.
        raise ProviderGenericError(user_msg=f"map source not available: {error}") from error
    except SourceNotDrawableError as error:
        raise ProviderGenericError(user_msg=f"map source not drawable: {error}") from error
    if bbox is None:
        bbox = [-HALF_WORLD, -HALF_WORLD, HALF_WORLD, HALF_WORLD]
    try:
        xmin, ymin, xmax, ymax = (_clamp(float(value)) for value in bbox)
        if xmin > xmax:
            # The west edge lies east of the east edge: the bbox crosses the
            # antimeridian, and its east edge is one world further on.
            xmax += 2 * HALF_WORLD
        return MapRequest(
            bbox=(xmin, ymin, xmax, ymax),
            width=int(width),
            height=int(height),
            style=chosen,
            transparent=transparent,
        )
    except ValueError as error:
        raise MapParameterError(user_msg=str(error)) from error


async def draw_map(queue: RenderQueue, request: MapRequest) -> bytes:
    """The PNG of ``request`` from ``queue``, with its outcomes as pygeoapi errors."""
    try:
        return await queue.draw(request)
    except QueueFullError:
        raise MapRendererBusyError() from None
    except DrawTimeoutError:
        raise MapRenderTimeoutError() from None
    except RenderError:
        raise ProviderGenericError(user_msg="the map renderer failed") from None
