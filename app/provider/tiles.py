"""OGC API Tiles from any registered tile source.

The provider answers pygeoapi: the tiles on both faces, the tileset
metadata, the TileJSON and the HTML page. Which source reads the tiles
comes from the registry of :mod:`app.tiles.sources`, or from the
subclass that names its own; what the tiles are comes from the
configuration and from the source's :class:`~app.tiles.contract.TileContent`.
A new backend is a source and its registration.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import PurePosixPath
from typing import Any, ClassVar

from pygeoapi.models.provider.base import (
    DataTypeEnum,
    LinkType,
    TileMatrixSetEnum,
    TileSetMetadata,
    TilesMetadataFormat,
)
from pygeoapi.provider.base import ProviderGenericError
from pygeoapi.provider.tile import BaseTileProvider, ProviderTileNotFoundError
from pygeoapi.util import url_join

from app.provider.base import AsyncProviderMixin, StorageBackedMixin
from app.provider.dem import check_dem
from app.provider.storage import SingleFlightRanges
from app.tiles.contract import (
    TileContent,
    TileOutsideError,
    TileSource,
    TileSourceError,
    VectorLayer,
    data_type_for,
    format_parameter,
)
from app.tiles.sources import TileSourceContext, tile_source_for

_KINDS = {"vector": "vector", "map": "map", "coverage": "elevation"}
"""The word the link titles use for the tiles of each data type."""


def _service_url(server_url: str, dataset: str, tileset: str, parameter: str) -> str:
    return url_join(
        server_url,
        f"collections/{dataset}/tiles/{tileset}/"
        f"{{tileMatrix}}/{{tileRow}}/{{tileCol}}?f={parameter}",
    )


def _xyz_url(server_url: str, dataset: str, tileset: str, parameter: str) -> str:
    # The same route with the placeholders MapLibre, Leaflet and QGIS substitute.
    return url_join(
        server_url, f"collections/{dataset}/tiles/{tileset}/{{z}}/{{y}}/{{x}}?f={parameter}"
    )


class TilesProvider(AsyncProviderMixin, StorageBackedMixin, BaseTileProvider):
    """Tiles read by the source the registry finds for ``data``, or the one a subclass names.

    Natively asynchronous: the tile route awaits the source. ``THREAD_SAFE``
    keeps one instance alive, which keeps the source and its caches.
    """

    THREAD_SAFE: ClassVar[bool] = True
    native_async: ClassVar[bool] = True
    source_builder: ClassVar[Callable[[TileSourceContext], TileSource] | None] = None
    """The source a subclass always uses; None asks the registry."""

    def __init__(self, provider_def: dict) -> None:
        """Check the options and build the source; the data is read at the first request.

        pygeoapi instantiates every tile provider while it writes the
        OpenAPI document, so nothing here may read the data.
        """
        super().__init__(provider_def)
        try:
            self.dem = check_dem(self.options.get("dem"))
        except ValueError as error:
            raise ProviderGenericError(user_msg=str(error)) from None
        build = type(self).source_builder
        if build is None:
            try:
                build = tile_source_for(self.data).build
            except LookupError as error:
                raise ProviderGenericError(user_msg=f"tile source not supported: {error}") from None
        self.data_type = data_type_for(self.mimetype, self.dem)
        # pygeoapi's own word, which its tilesets page reads to pick how to draw the tiles.
        self.tile_type = "vector" if self.data_type == "vector" else "raster"
        self.source = build(
            TileSourceContext(
                data=self.data,
                options=self.options,
                media_type=self.mimetype,
                dem=self.dem,
                ranges=lambda: SingleFlightRanges(self.byte_ranges()),
                cached=lambda: self.cached_ranges,
                offload=self.run_sync,
            )
        )

    def __repr__(self) -> str:
        """The data this provider serves."""
        return f"<{type(self).__name__}> {self.data}"

    # -- the two faces -----------------------------------------------------------

    def get_tiles(self, layer=None, tileset=None, z=None, y=None, x=None, format_=None):
        """The tile bytes, decompressed; pygeoapi's synchronous contract."""
        z, x, y = self._within_limits(z, x, y)
        try:
            return self.source.tile(z, x, y)
        except TileOutsideError as error:
            raise ProviderTileNotFoundError(str(error)) from None
        except TileSourceError as error:
            raise ProviderGenericError(user_msg=str(error)) from None

    async def aget_tiles(self, layer=None, tileset=None, z=None, y=None, x=None, format_=None):
        """The same tile, awaited.

        Same signature as ``get_tiles``, defaults included, so
        ``async_view`` can call either face with the same keywords.
        """
        z, x, y = self._within_limits(z, x, y)
        try:
            return await self.source.atile(z, x, y)
        except TileOutsideError as error:
            raise ProviderTileNotFoundError(str(error)) from None
        except TileSourceError as error:
            raise ProviderGenericError(user_msg=str(error)) from None

    async def aversion(self, layer=None, tileset=None, z=None, y=None, x=None, format_=None):
        """The version of the tile ``aget_tiles`` would answer: the archive's and the definition's.

        Same signature as ``aget_tiles``. None when the archive's version is
        unknown, and for a tile outside the limits, which answers 404
        whatever the version.
        """
        try:
            self._within_limits(z, x, y)
        except ProviderTileNotFoundError:
            return None
        data = await self.adata_version()
        return None if data is None else f"{data}|{self.definition_digest()}"

    def _within_limits(self, z: Any, x: Any, y: Any) -> tuple[int, int, int]:
        """Pygeoapi's semantics: a tile outside the configured limits is 404.

        Non-numeric coordinates (a URL template pasted literally) count as
        outside the limits and answer 404, as pygeoapi's own
        ``is_in_limits`` treats them.
        """
        try:
            z, x, y = int(z), int(x), int(y)
        except (TypeError, ValueError):
            raise ProviderTileNotFoundError(
                f"tile coordinates {z}/{x}/{y} are not numbers"
            ) from None
        zoom = self.options["zoom"]
        scheme = TileMatrixSetEnum.WEBMERCATORQUAD.value
        # The zoom first: is_in_limits indexes the tile matrices by it.
        if not zoom["min"] <= z <= zoom["max"] or not self.is_in_limits(scheme, z, x, y):
            raise ProviderTileNotFoundError(f"tile {z}/{x}/{y} is outside the configured limits")
        return z, x, y

    # -- what pygeoapi asks besides tiles ---------------------------------------

    def get_layer(self):
        """The layer name: the data's file stem, like the tippecanoe provider's directory."""
        return PurePosixPath(self.object_key).stem

    def get_fields(self):
        """Tiles carry no queryable fields."""
        return {}

    def get_tiling_schemes(self):
        """Web Mercator z/x/y, the scheme of every registered backend."""
        return [TileMatrixSetEnum.WEBMERCATORQUAD.value]

    def get_tiles_service(self, baseurl=None, servicepath=None, dirpath=None, tile_type=None):
        """The links pygeoapi lists under ``/tiles``, from the configuration alone."""
        tilesets = servicepath.split("/{tileMatrix}/{tileRow}/{tileCol}")[0]
        kind = _KINDS[self.data_type]
        return {
            "links": [
                {
                    "type": "application/json",
                    "rel": "self",
                    "title": f"This collection as multi {kind} tilesets",
                    "href": f"{tilesets}?f=json",
                },
                {
                    "type": self.mimetype,
                    "rel": "item",
                    "title": f"This collection as multi {kind} tiles",
                    "href": servicepath,
                },
                {
                    "type": "application/json",
                    "rel": "describedby",
                    "title": "Collection metadata in TileJSON format",
                    "href": f"{url_join(tilesets, 'metadata')}?f=json",
                },
            ]
        }

    # pygeoapi's API calls this with these arguments (api/tiles.py), as its own
    # BaseMVTProvider declares them; BaseTileProvider's stub takes none.
    def get_metadata(  # ty: ignore[invalid-method-override]
        self,
        dataset,
        server_url,
        layer=None,
        tileset=None,
        metadata_format=None,
        title=None,
        description=None,
        keywords=None,
        **kwargs,
    ):
        """Tileset metadata in the format pygeoapi asks: OGC JSON or JSON-LD, TileJSON or HTML."""
        wanted = (metadata_format or "").upper()
        arguments = (dataset, server_url, layer, tileset, title, description, keywords)
        if wanted in (TilesMetadataFormat.JSON, TilesMetadataFormat.JSONLD):
            return self.get_default_metadata(*arguments, **kwargs)
        if wanted == TilesMetadataFormat.TILEJSON:
            return self.get_vendor_metadata(*arguments, **kwargs)
        if wanted == TilesMetadataFormat.HTML:
            return self.get_html_metadata(*arguments, **kwargs)
        raise NotImplementedError(f"_{wanted}_ is not supported")

    def get_default_metadata(
        self, dataset, server_url, layer, tileset, title, description, keywords, **kwargs
    ):
        """OGC tileset metadata, from the configuration alone."""
        scheme = next((s for s in self.get_tiling_schemes() if s.tileMatrixSet == tileset), None)
        if scheme is None:
            raise ProviderTileNotFoundError(f"tile matrix set {tileset} is not served")
        content = TileSetMetadata(
            title=title,
            description=description,
            keywords=keywords,
            crs=scheme.crs,
            tileMatrixSetURI=scheme.tileMatrixSetURI,
            dataType=DataTypeEnum(self.data_type),
        )
        content.links = [
            LinkType(
                **{
                    "href": url_join(server_url, f"/TileMatrixSets/{scheme.tileMatrixSet}"),
                    "rel": "http://www.opengis.net/def/rel/ogc/1.0/tiling-scheme",
                    "type": "application/json",
                    "title": f"{scheme.tileMatrixSet} tile matrix set definition",
                }
            ),
            LinkType(
                **{
                    "href": _service_url(
                        server_url, dataset, tileset, format_parameter(self.mimetype)
                    ),
                    "rel": "item",
                    "type": self.mimetype,
                    "title": f"{tileset} {_KINDS[self.data_type]} tiles for {layer}",
                }
            ),
        ]
        return content.model_dump(exclude_none=True, by_alias=True)

    def get_vendor_metadata(
        self, dataset, server_url, layer, tileset, title, description, keywords, **kwargs
    ):
        """TileJSON, from what the source holds."""
        try:
            content = self.source.content()
        except TileSourceError as error:
            raise ProviderGenericError(user_msg=str(error)) from None
        if content.data_type == "vector":
            return _vector_tilejson(content, dataset, server_url, tileset)
        return _raster_tilejson(content, dataset, server_url, tileset)

    def get_html_metadata(
        self, dataset, server_url, layer, tileset, title, description, keywords, **kwargs
    ):
        """What the HTML template renders: the TileJSON plus the URLs around it."""
        metadata_url = url_join(server_url, f"collections/{dataset}/tiles/{tileset}/metadata")
        return {
            "id": dataset,
            "title": title,
            "tileset": tileset,
            "collections_path": _service_url(
                server_url, dataset, tileset, format_parameter(self.mimetype)
            ),
            "json_url": f"{metadata_url}?f=json",
            "tilejson_url": f"{metadata_url}?f=tilejson",
            "metadata": self.get_vendor_metadata(
                dataset, server_url, layer, tileset, title, description, keywords
            ),
        }


def _tilejson(content: TileContent, dataset: str, server_url: str, tileset: str) -> dict[str, Any]:
    """The TileJSON 3.0.0 keys of every tileset, in the shape MapLibre reads as a source."""
    tilejson: dict[str, Any] = {
        "tilejson": "3.0.0",
        "name": content.name or dataset,
        "tiles": [_xyz_url(server_url, dataset, tileset, content.format_parameter)],
        "minzoom": content.min_zoom,
        "maxzoom": content.max_zoom,
        "bounds": list(content.bounds),
        "center": list(content.center),
    }
    if content.description:
        tilejson["description"] = content.description
    if content.attribution:
        tilejson["attribution"] = content.attribution
    return tilejson


def _vector_tilejson(content: TileContent, dataset: str, server_url: str, tileset: str) -> dict:
    """TileJSON 3.0.0 for a vector source, with its layers."""
    tilejson = _tilejson(content, dataset, server_url, tileset)
    tilejson["vector_layers"] = [_vector_layer(layer) for layer in content.layers]
    return tilejson


def _vector_layer(layer: VectorLayer) -> dict[str, Any]:
    """One entry of ``vector_layers``: ``id`` and ``fields`` always, the rest when known."""
    entry: dict[str, Any] = {"id": layer.id, "fields": dict(layer.fields or {})}
    if layer.description:
        entry["description"] = layer.description
    if layer.minzoom is not None:
        entry["minzoom"] = layer.minzoom
    if layer.maxzoom is not None:
        entry["maxzoom"] = layer.maxzoom
    return entry


def _raster_tilejson(content: TileContent, dataset: str, server_url: str, tileset: str) -> dict:
    """TileJSON 3.0.0 for a raster or raster-dem source, with the tile size and the encoding."""
    tilejson = _tilejson(content, dataset, server_url, tileset)
    if content.tile_size:
        tilejson["tileSize"] = content.tile_size
    if content.dem is not None:
        tilejson["encoding"] = content.dem
    return tilejson
