"""PMTiles archives as tile providers of fastgeoapi.

The archive is the collection's ``visual`` asset of type
``application/vnd.pmtiles``, or else its ``rel: pmtiles`` link. The
catalog gives neither the zoom nor the tile format, so both are read from
the archive by range: the header, then the metadata. The ``style`` assets
of the collection become its named styles.
"""

from __future__ import annotations

import json
import zlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from obstore.exceptions import BaseError
from pmtiles.tile import (
    Compression,
    MagicNumberNotFound,
    SpecVersionUnsupported,
    TileType,
    deserialize_header,
)

from fastgeoapi_portolan.catalog.locations import (
    LOCAL_FROM_REMOTE,
    is_local_from_remote,
    is_url,
    resolve,
)
from fastgeoapi_portolan.handlers import (
    IngestOptions,
    ProviderMatch,
    Refusal,
    describe_read_error,
    is_transient,
)
from fastgeoapi_portolan.reader import Collection
from fastgeoapi_portolan.storage import read_bytes, read_range

PROVIDER = "app.provider.pmtiles.PMTilesProvider"
PMTILES = "application/vnd.pmtiles"
HEADER_LENGTH = 127
FORMATS = {
    TileType.MVT: {"name": "pbf", "mimetype": "application/vnd.mapbox-vector-tile"},
    TileType.PNG: {"name": "png", "mimetype": "image/png"},
    TileType.JPEG: {"name": "jpg", "mimetype": "image/jpeg"},
    TileType.WEBP: {"name": "webp", "mimetype": "image/webp"},
    TileType.AVIF: {"name": "avif", "mimetype": "image/avif"},
}
_SCHEME = "pmtiles://"


def style_name(key: str, asset: Mapping[str, Any]) -> str:
    """The name of a style asset: its ``title``, or its key without ``style-`` and ``-style``."""
    title = asset.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    return key.removeprefix("style-").removesuffix("-style") or key


def _media_type(value: Any) -> str:
    return str(value or "").split(";", 1)[0].strip()


def _roles(asset: Mapping[str, Any]) -> list[str]:
    roles = asset.get("roles")
    return [role for role in roles if isinstance(role, str)] if isinstance(roles, list) else []


def _assets(document: Mapping[str, Any]) -> list[tuple[str, Mapping[str, Any]]]:
    assets = document.get("assets")
    if not isinstance(assets, Mapping):
        return []
    return [
        (key, asset)
        for key, asset in assets.items()
        if isinstance(asset, Mapping) and isinstance(asset.get("href"), str) and asset["href"]
    ]


def _archive(collection: Collection) -> tuple[str, str] | None:
    """Where the archive is, and what named it."""
    for _, asset in _assets(collection.document):
        if "visual" in _roles(asset) and _media_type(asset.get("type")) == PMTILES:
            return resolve(collection.href, asset["href"]), "visual asset"
    links = collection.document.get("links")
    for link in links if isinstance(links, list) else ():
        if isinstance(link, Mapping) and link.get("rel") == "pmtiles":
            href = link.get("href")
            if isinstance(href, str) and href:
                return resolve(collection.href, href), "pmtiles link"
    return None


def _file_name(location: str) -> str:
    return urlsplit(location).path.rsplit("/", 1)[-1] if is_url(location) else Path(location).name


def _archive_source(style: Any, style_href: str, archive: str) -> str | None:
    """The name of the source of ``style`` that reads ``archive``.

    A style may reach the archive through another URL than the catalog's,
    a CDN in front of the bucket for example, so when the URLs differ the
    file name decides.
    """
    sources = style.get("sources") if isinstance(style, Mapping) else None
    for name, source in sources.items() if isinstance(sources, Mapping) else ():
        url = source.get("url") if isinstance(source, Mapping) else None
        if not isinstance(url, str) or not url.startswith(_SCHEME):
            continue
        target = resolve(style_href, url[len(_SCHEME) :])
        if target == archive or _file_name(target) == _file_name(archive):
            return str(name)
    return None


def _gunzip(data: bytes, limit: int) -> bytes:
    """``data`` decompressed, or ``ValueError`` once it grows past ``limit`` bytes."""
    inflater = zlib.decompressobj(wbits=16 + zlib.MAX_WBITS)
    inflated = inflater.decompress(data, limit + 1)
    if len(inflated) > limit:
        raise ValueError(f"the metadata inflates past {limit} bytes")
    return inflated


async def _zoom(
    location: str, header: Mapping[str, Any], ingest_options: IngestOptions
) -> tuple[dict[str, int], str] | Refusal:
    """The zoom span of the ``vector_layers`` in the metadata, or else the header's.

    The header gives the size of the metadata, so it is read and
    decompressed only within the document cap. Metadata that cannot be read
    now refuses the archive for now.
    """
    limit = ingest_options.max_document_bytes
    try:
        if header["metadata_length"] > limit:
            raise ValueError(f"the metadata is larger than {limit} bytes")
        raw = await read_range(
            location,
            header["metadata_offset"],
            header["metadata_length"],
            ingest_options.store_options,
        )
        if header["internal_compression"] == Compression.GZIP:
            raw = _gunzip(raw, limit)
        elif header["internal_compression"] != Compression.NONE:
            raise ValueError("compression not read")
        layers = json.loads(raw).get("vector_layers")
        spans = [
            (layer["minzoom"], layer["maxzoom"])
            for layer in layers
            if isinstance(layer.get("minzoom"), int) and isinstance(layer.get("maxzoom"), int)
        ]
    except (OSError, BaseError) as error:
        if is_transient(error):
            reason = f"the archive metadata could not be read: {describe_read_error(error)}"
            return Refusal(reason, transient=True)
        spans = []
    except (ValueError, AttributeError, TypeError, zlib.error):
        spans = []
    if spans:
        return {
            "min": min(low for low, _ in spans),
            "max": max(high for _, high in spans),
        }, "vector_layers"
    return {"min": header["min_zoom"], "max": header["max_zoom"]}, "header"


async def _styles(
    collection: Collection, archive: str, ingest_options: IngestOptions
) -> tuple[dict[str, Any], list[str]] | Refusal:
    """The style options for the provider, and the choices behind them.

    A style that cannot be read now refuses the archive for now, so a
    second ingest does not drop it from the provider.
    """
    named: list[tuple[str, str, bool]] = []
    for key, asset in _assets(collection.document):
        roles = _roles(asset)
        if "style" in roles:
            named.append(
                (
                    style_name(key, asset),
                    resolve(collection.href, asset["href"]),
                    "default" in roles,
                )
            )
    # The default leads: it opens the pages, and it names the archive for the others.
    named.sort(key=lambda entry: not entry[2])

    choices: list[str] = []
    sources: dict[str, tuple[str, str | None]] = {}
    for name, href, _ in named:
        if name in sources:
            choices.append(f"styles: {name} left out: another style has the name")
            continue
        if is_local_from_remote(collection.href, href):
            choices.append(f"styles: {name} left out: it {LOCAL_FROM_REMOTE}")
            continue
        try:
            raw = await read_bytes(
                href, ingest_options.store_options, max_bytes=ingest_options.max_document_bytes
            )
            style = json.loads(raw)
        except (OSError, BaseError) as error:
            why = describe_read_error(error)
            if is_transient(error):
                return Refusal(f"the style {name} could not be read: {why}", transient=True)
            choices.append(f"styles: {name} left out: it could not be read: {why}")
            continue
        except ValueError:
            choices.append(f"styles: {name} left out: it is not JSON")
            continue
        sources[name] = (href, _archive_source(style, href, archive))

    reference = next((source for _, source in sources.values() if source), None)
    kept: dict[str, str] = {}
    for name, (href, source) in sources.items():
        if source is None:
            choices.append(f"styles: {name} left out: none of its sources reads the archive")
        elif source != reference:
            choices.append(
                f"styles: {name} left out: it calls the archive {source}, the others {reference}"
            )
        else:
            kept[name] = href
    if not kept:
        return {}, choices

    options: dict[str, Any] = {"styles": kept}
    choices.insert(0, f"styles: {', '.join(kept)}")
    default = next((name for name, _, is_default in named if is_default), None)
    if default in kept:
        options["default_style"] = default
        choices.append(f"default_style: {default} (role default)")
    options["style_source"] = reference
    choices.append(f"style_source: {reference} (the source that reads the archive)")
    return options, choices


async def pmtiles_provider(
    collection: Collection, ingest_options: IngestOptions
) -> ProviderMatch | Refusal | None:
    """The tile provider for the PMTiles archive of ``collection``."""
    found = _archive(collection)
    if found is None:
        return None
    location, origin = found
    if is_local_from_remote(collection.href, location):
        return Refusal(f"the archive {location} {LOCAL_FROM_REMOTE}")
    try:
        raw = await read_range(location, 0, HEADER_LENGTH, ingest_options.store_options)
    except (OSError, BaseError) as error:
        reason = f"the archive could not be read: {describe_read_error(error)}"
        return Refusal(reason, transient=is_transient(error))
    try:
        header = deserialize_header(raw)
    except (MagicNumberNotFound, SpecVersionUnsupported, ValueError, IndexError) as error:
        return Refusal(f"the archive header could not be read: {describe_read_error(error)}")
    tile_type = header["tile_type"]
    tile_format = FORMATS.get(tile_type)
    if tile_format is None:
        return Refusal(f"tile type {TileType(tile_type).name} is not served by the provider")

    zoomed = await _zoom(location, header, ingest_options)
    if isinstance(zoomed, Refusal):
        return zoomed
    styled = await _styles(collection, location, ingest_options)
    if isinstance(styled, Refusal):
        return styled
    zoom, zoom_origin = zoomed
    style_options, style_choices = styled
    provider: dict[str, Any] = {
        "type": "tile",
        "name": PROVIDER,
        "data": location,
        "options": {"zoom": zoom, "schemes": ["WebMercatorQuad"], **style_options},
        "format": dict(tile_format),
    }
    if ingest_options.store_options:
        provider["store_options"] = dict(ingest_options.store_options)
    choices = (
        f"data: {origin}",
        f"zoom: {zoom['min']}-{zoom['max']} ({zoom_origin})",
        f"format: {tile_format['name']} (tile type {TileType(tile_type).name})",
        *style_choices,
    )
    return ProviderMatch(provider, choices)
