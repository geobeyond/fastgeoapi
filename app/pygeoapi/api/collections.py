"""Override module for pygeoapi's collections endpoint.

pygeoapi's ``gen_collection`` decides a collection's ``itemType`` and
``items`` links from its default provider. Tiles in any format but png or
jpeg count as vector tiles and get both, whether or not a feature or record
provider serves the items: a collection of PMTiles alone, vector or WebP,
links to an ``/items`` route that answers 404. Tiles in png or jpeg get
neither, even beside a feature provider, and vector tiles beside one get
``itemType: tile``. This is pygeoapi's ``describe_collections`` with one
change: every collection goes through :func:`match_items_to_providers`. It
can go once pygeoapi looks at all the providers.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

from pygeoapi import l10n
from pygeoapi.api.collection import gen_collection
from pygeoapi.crs import DEFAULT_CRS, transform_bbox
from pygeoapi.formats import F_HTML, F_JSON, F_JSONLD, FORMAT_TYPES
from pygeoapi.linked_data import jsonldify, jsonldify_collection
from pygeoapi.util import (
    filter_dict_by_key_value,
    get_dataset_formatters,
    render_j2_template,
    to_json,
)

from app.config.logging import create_logger
from app.interfaces.providers import MapFormat
from app.provider.maps import WEB_MERCATOR
from app.pygeoapi.api_async.map_parameters import clip_bbox
from app.pygeoapi.api_async.maps import find_native_map_provider
from app.pygeoapi.map_limits import choose_default_map_crs

if TYPE_CHECKING:
    from pygeoapi.api import API, APIRequest

logger = create_logger("app.pygeoapi.api.collections")

ITEM_PROVIDERS = ("feature", "record")
"""The provider types that serve ``/items``, in the order pygeoapi's items route tries them."""


def item_provider_type(providers: list[dict]) -> str | None:
    """The type of the provider that answers ``/items``, or None when none can."""
    types = {provider.get("type") for provider in providers}
    return next((kind for kind in ITEM_PROVIDERS if kind in types), None)


def items_links(api: API, request: APIRequest, dataset: str) -> list[dict]:
    """The ``items`` links pygeoapi gives a collection it describes from its feature provider."""
    url = f"{api.get_collections_url()}/{dataset}/items"
    links = [
        {
            "type": "application/geo+json",
            "rel": "items",
            "title": l10n.translate("Items as GeoJSON", request.locale),
            "href": f"{url}?f={F_JSON}",
        },
        {
            "type": FORMAT_TYPES[F_JSONLD],
            "rel": "items",
            "title": l10n.translate("Items as RDF (GeoJSON-LD)", request.locale),
            "href": f"{url}?f={F_JSONLD}",
        },
        {
            "type": FORMAT_TYPES[F_HTML],
            "rel": "items",
            "title": l10n.translate("Items as HTML", request.locale),
            "href": f"{url}?f={F_HTML}",
        },
    ]
    for key, value in get_dataset_formatters(api.config["resources"][dataset]).items():
        links.append(
            {
                "type": value.mimetype,
                "rel": "items",
                "title": l10n.translate(f"Items as {key}", request.locale),
                "href": f"{url}?f={value.f}",
            }
        )
    return links


def match_items_to_providers(api: API, request: APIRequest, dataset: str, collection: dict) -> dict:
    """``itemType`` and ``items`` links on ``collection`` exactly when a provider serves items."""
    item_type = item_provider_type(api.config["resources"][dataset]["providers"])
    others = [link for link in collection["links"] if link.get("rel") != "items"]
    if item_type is None:
        collection.pop("itemType", None)
        collection["links"] = others
        return collection
    collection["itemType"] = item_type
    if len(others) == len(collection["links"]):
        # pygeoapi left them out: the default provider serves raster tiles or maps.
        collection["links"].extend(items_links(api, request, dataset))
    return collection


_MAP_REL = "http://www.opengis.net/def/rel/ogc/1.0/map"
_MERCATOR_LATITUDE = 85.0511287798
"""The latitude where Web Mercator ends."""


def describe_native_map(api: API, dataset: str, collection: dict) -> dict:
    """Describe the map of ``collection`` from its native map provider.

    The collection lists the CRSs its maps are drawn in, with ``storageCrs``
    and ``storageCrsBbox`` when they are drawn by default in a CRS other than
    CRS84 (/req/collection-map/desc-crs), and links one map per encoding
    (/req/collection-map/desc-links).

    Parameters
    ----------
    api
        pygeoapi's API instance.
    dataset
        The collection's name.
    collection
        The collection as pygeoapi described it; changed in place.

    Returns
    -------
    dict
        ``collection``, unchanged when its map provider is not native.
    """
    found = find_native_map_provider(api, dataset)
    if found is None:
        return collection
    definition, provider = found
    capabilities = provider.capabilities
    listed = list(collection.get("crs") or [])
    collection["crs"] = listed + [crs for crs in capabilities.crs if crs not in listed]
    storage = choose_default_map_crs(definition, capabilities)
    if "storageCrs" not in collection and storage.lower() != DEFAULT_CRS.lower():
        collection["storageCrs"] = storage
        spatial = collection.get("extent", {}).get("spatial") or {}
        boxes = [_project_bbox(bbox, storage) for bbox in spatial.get("bbox") or []]
        if spatial and all(boxes):
            spatial["storageCrsBbox"] = boxes
    url = f"{api.get_collections_url()}/{dataset}/map"
    links = [link for link in collection["links"] if link.get("rel") != _MAP_REL]
    for format_ in capabilities.formats:
        encoding = MapFormat(format_)
        links.append(
            {
                "type": encoding.media_type,
                "rel": _MAP_REL,
                "title": f"Map ({encoding.value})",
                "href": f"{url}?f={encoding.value}",
            }
        )
    collection["links"] = links
    return collection


def _project_bbox(bbox: list, crs: str) -> list[float] | None:
    """Move a CRS84 ``bbox`` into ``crs``, inside its bounds; None when nothing is left.

    Parameters
    ----------
    bbox
        Four CRS84 coordinates.
    crs
        The URI of the target CRS.

    Returns
    -------
    list of float or None
        The four coordinates in ``crs``.
    """
    minx, miny, maxx, maxy = (float(value) for value in bbox[:4])
    if crs.lower() == WEB_MERCATOR.lower():
        # Web Mercator has no y for the poles: the transform would give infinity.
        miny = max(miny, -_MERCATOR_LATITUDE)
        maxy = min(maxy, _MERCATOR_LATITUDE)
    moved = transform_bbox([minx, miny, maxx, maxy], DEFAULT_CRS, crs, always_xy=True)
    clipped = clip_bbox((moved[0], moved[1], moved[2], moved[3]), crs)
    return list(clipped) if clipped is not None else None


@jsonldify
def describe_collections(
    api: API, request: APIRequest, dataset: str | None = None
) -> tuple[dict, int, str]:
    """Collection metadata as pygeoapi gives it, with the items described by their provider.

    :param api: API instance
    :param request: APIRequest instance
    :param dataset: name of one collection, or None for all of them

    :returns: tuple of headers, status code, content
    """
    headers = request.get_response_headers(**api.api_headers)
    collections = filter_dict_by_key_value(api.config["resources"], "type", "collection")

    if dataset is not None and dataset not in collections:
        return api.get_exception(
            HTTPStatus.NOT_FOUND, headers, request.format, "NotFound", "Collection not found"
        )

    described = {dataset: collections[dataset]} if dataset is not None else collections
    fcm: dict = {"collections": [], "links": []}
    for name, resource in described.items():
        if resource.get("visibility", "default") == "hidden" and dataset is None:
            continue
        try:
            collection = gen_collection(api, request, name, request.locale)
        except Exception as error:
            # pygeoapi's behaviour: the list skips a collection it cannot describe.
            logger.warning(f"Error generating collection {name}: {error}")
            if dataset is not None:
                return api.get_exception(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    headers,
                    request.format,
                    "NoApplicableCode",
                    "Error generating collection",
                )
            continue
        collection = match_items_to_providers(api, request, name, collection)
        fcm["collections"].append(describe_native_map(api, name, collection))

    if dataset is not None:
        fcm = fcm["collections"][0]
    else:
        url = api.get_collections_url()
        for format_, title in (
            (F_JSON, "This document as JSON"),
            (F_JSONLD, "This document as RDF (JSON-LD)"),
            (F_HTML, "This document as HTML"),
        ):
            fcm["links"].append(
                {
                    "type": FORMAT_TYPES[format_],
                    "rel": request.get_linkrel(format_),
                    "title": l10n.translate(title, request.locale),
                    "href": f"{url}?f={format_}",
                }
            )

    if request.format == F_HTML:
        fcm["base_url"] = api.base_url
        fcm["collections_path"] = api.get_collections_url()
        if dataset is not None:
            content = render_j2_template(
                api.tpl_config,
                api.get_dataset_templates(dataset),
                "collections/collection.html",
                fcm,
                request.locale,
            )
        else:
            content = render_j2_template(
                api.tpl_config,
                api.config["server"]["templates"],
                "collections/index.html",
                fcm,
                request.locale,
            )
        return headers, HTTPStatus.OK, content

    if request.format == F_JSONLD:
        jsonld = api.fcmld.copy()
        if dataset is not None:
            jsonld["dataset"] = jsonldify_collection(api, fcm, request.locale)
        else:
            jsonld["dataset"] = [
                jsonldify_collection(api, collection, request.locale)
                for collection in fcm["collections"]
            ]
        return headers, HTTPStatus.OK, to_json(jsonld, api.pretty_print)

    return headers, HTTPStatus.OK, to_json(fcm, api.pretty_print)
