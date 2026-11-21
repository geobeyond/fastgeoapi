"""The OGC URIs fastgeoapi uses: conformance classes, link relations and CRSs.

A name says what kind of URI it holds. ``<SPEC>_CONFORMANCE_PREFIX`` starts
the conformance classes of one OGC API standard, such as
``MAPS_CONFORMANCE_PREFIX``. ``OGC_REL_<NAME>`` is a link relation of the
OGC register at ``http://www.opengis.net/def/rel/ogc/1.0/``, which every OGC
API standard shares: ``<NAME>`` is the relation's name in upper case, with
``_`` for ``-``, as in ``OGC_REL_TILING_SCHEME``.
"""

MAPS_CONFORMANCE_PREFIX = "http://www.opengis.net/spec/ogcapi-maps-1/1.0/conf"
"""The start of the URI of every OGC API - Maps conformance class."""

OGC_REL_MAP = "http://www.opengis.net/def/rel/ogc/1.0/map"
"""The link from a collection to its map (/req/collection-map/desc-links)."""
