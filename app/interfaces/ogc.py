"""The OGC URIs fastgeoapi uses: conformance classes, link relations and CRSs.

A name says what kind of URI it holds. ``<SPEC>_CONFORMANCE_PREFIX`` starts
the conformance classes of one OGC API standard, such as
``MAPS_CONFORMANCE_PREFIX``. ``OGC_REL_<NAME>`` is a link relation of the
OGC registry at ``http://www.opengis.net/def/rel/ogc/1.0/``, which every OGC
API standard shares: ``<NAME>`` is the relation's name in upper case, with
``_`` for ``-``, as in ``OGC_REL_TILING_SCHEME``. ``OGC_REL_PREFIX`` is
for a family of relations, such as ``tilesets-vector`` and ``tilesets-map``.
``OGC_CRS_<NAME>`` is a CRS of the OGC registry at
``http://www.opengis.net/def/crs/``, named by its common name, as in
``OGC_CRS_WEB_MERCATOR``.
"""

OGC_CRS_WEB_MERCATOR = "http://www.opengis.net/def/crs/EPSG/0/3857"
"""Web Mercator, EPSG:3857."""

MAPS_CONFORMANCE_PREFIX = "http://www.opengis.net/spec/ogcapi-maps-1/1.0/conf"
"""The start of the URI of every OGC API - Maps conformance class."""

OGC_REL_PREFIX = "http://www.opengis.net/def/rel/ogc/1.0/"
"""The start of the URI of every link relation of the OGC register."""

OGC_REL_MAP = f"{OGC_REL_PREFIX}map"
"""The link from a collection to its map (/req/collection-map/desc-links)."""

OGC_REL_QUERYABLES = f"{OGC_REL_PREFIX}queryables"
"""The link from a collection to its queryables."""

OGC_REL_SCHEMA = f"{OGC_REL_PREFIX}schema"
"""The link from a collection to the schema of its items."""

OGC_REL_COVERAGE = f"{OGC_REL_PREFIX}coverage"
"""The link from a collection to its coverage."""

OGC_REL_TILING_SCHEME = f"{OGC_REL_PREFIX}tiling-scheme"
"""The link from a tileset to the definition of its tile matrix set."""

OGC_REL_TILING_SCHEMES = f"{OGC_REL_PREFIX}tiling-schemes"
"""The link from the landing page to the tile matrix sets."""

OGC_REL_PROCESSES = f"{OGC_REL_PREFIX}processes"
"""The link from the landing page to the list of processes."""

OGC_REL_JOB_LIST = f"{OGC_REL_PREFIX}job-list"
"""The link from the landing page to the list of jobs."""

OGC_REL_EXECUTE = f"{OGC_REL_PREFIX}execute"
"""The link from a process to the endpoint that executes it."""
