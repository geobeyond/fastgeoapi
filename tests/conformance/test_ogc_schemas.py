"""Validate the JSON fastgeoapi returns against the official OGC schemas."""

from typing import Any
from urllib.parse import urlsplit

import pytest

from tests.conformance.conftest import Served

validate_response = pytest.importorskip("xpublish_ogc_core.testing").validate_response

_REASON_NULLABLE = (
    "The OGC schema marks the ends of an interval `nullable: true`, an OpenAPI 3.0"
    " keyword the Draft 7 validator ignores; null is the standard's open end."
)

#: Violations that are not fastgeoapi's, keyed by component schema and JSON
#: path, with the reason. An entry that stops occurring fails the last test.
KNOWN_DIVERGENCES: dict[tuple[str, str], str] = {
    ("collection", "$.extent.temporal.interval[0][1]"): _REASON_NULLABLE,
    ("collections", "$.collections[1].extent.temporal.interval[0][1]"): _REASON_NULLABLE,
}

#: The known divergences the responses have met so far.
SEEN: set[tuple[str, str]] = set()


def get_json(served: Served, path: str) -> tuple[int, Any]:
    """Request the JSON representation of a path.

    Parameters
    ----------
    served
        The configuration to ask.
    path
        The path under the sub-app, without the ``f`` parameter.

    Returns
    -------
    tuple[int, Any]
        The status code and the decoded body.
    """
    response = served.client.get(path, params={"f": "json"})
    return response.status_code, response.json()


def assert_follows_ogc(name: str, body: Any, document: str) -> None:
    """Validate a body against an OGC component schema, allowing the known divergences.

    Parameters
    ----------
    name
        The component schema, such as ``collection``.
    body
        The decoded JSON body.
    document
        The OGC document the schema comes from: ``common`` or ``tiles``.

    Raises
    ------
    AssertionError
        If the body breaks the schema anywhere ``KNOWN_DIVERGENCES`` does not list.
    """
    try:
        validate_response(name, body, document=document)
    except AssertionError as error:
        lines = str(error).splitlines()
        violations = [line.strip() for line in lines[1:]]
        unknown = []
        for violation in violations:
            path = violation.split(": ", 1)[0]
            if (name, path) in KNOWN_DIVERGENCES:
                SEEN.add((name, path))
            else:
                unknown.append(violation)
        if unknown:
            raise AssertionError("\n".join([lines[0], *unknown])) from None


def test_the_landing_page_follows_ogc_common(served: Served) -> None:
    """The landing page is a Common Part 1 ``landingPage``."""
    status, body = get_json(served, "/")

    assert status == 200
    assert_follows_ogc("landingPage", body, "common")


def list_tileset_paths(served: Served) -> list[str]:
    """Find the tilesets the tile collections link to.

    The paths come from the ``self`` links of ``/collections/{id}/tiles``,
    so a collection is asked only for the tile matrix sets it publishes.

    Parameters
    ----------
    served
        The configuration to ask.

    Returns
    -------
    list[str]
        The path of each tileset under the sub-app, without its query.
    """
    base = urlsplit(served.config["server"]["url"]).path.rstrip("/")
    paths = []
    for name, resource in served.config["resources"].items():
        if not any(provider["type"] == "tile" for provider in resource.get("providers", [])):
            continue
        status, body = get_json(served, f"/collections/{name}/tiles")
        assert status == 200, name
        for tileset in body["tilesets"]:
            href = next(link["href"] for link in tileset["links"] if link["rel"] == "self")
            paths.append(urlsplit(href).path.removeprefix(base))
    return paths


def list_collection_names(served: Served) -> list[str]:
    """Name the resources of the configuration that are collections.

    Parameters
    ----------
    served
        The configuration to read.

    Returns
    -------
    list[str]
        The names, in the order of the configuration.
    """
    return [
        name
        for name, resource in served.config["resources"].items()
        if resource["type"] == "collection"
    ]


def test_the_conformance_declaration_follows_ogc_common(served: Served) -> None:
    """The conformance declaration is a Common Part 1 ``confClasses``."""
    status, body = get_json(served, "/conformance")

    assert status == 200
    assert_follows_ogc("confClasses", body, "common")


def test_the_collections_follow_ogc_common(served: Served) -> None:
    """The list of collections follows the ``collections`` schema."""
    status, body = get_json(served, "/collections")

    assert status == 200
    assert_follows_ogc("collections", body, "common")


def test_each_collection_follows_ogc_common(served: Served) -> None:
    """Every collection of the configuration follows the ``collection`` schema."""
    for name in list_collection_names(served):
        status, body = get_json(served, f"/collections/{name}")

        assert status == 200, name
        assert_follows_ogc("collection", body, "common")


def test_an_unknown_collection_answers_an_ogc_exception(served: Served) -> None:
    """A collection that does not exist answers a Common Part 1 ``exception``."""
    status, body = get_json(served, "/collections/nope")

    assert status == 404
    assert_follows_ogc("exception", body, "common")


def test_each_tileset_follows_ogc_tiles(served: Served) -> None:
    """Every tileset a tile collection links to follows the Tiles ``tileSet`` schema."""
    paths = list_tileset_paths(served)
    if not paths:
        pytest.skip("the configuration has no tile collection")
    for path in paths:
        status, body = get_json(served, path)

        assert status == 200, path
        assert_follows_ogc("tileSet", body, "tiles")


def test_an_unlisted_divergence_fails() -> None:
    """A violation that ``KNOWN_DIVERGENCES`` does not list fails the test."""
    with pytest.raises(AssertionError, match="'links' is a required property"):
        assert_follows_ogc("landingPage", {}, "common")


# Keep this test last: it reads what the tests above recorded.
def test_a_known_divergence_that_no_longer_occurs_fails(request: pytest.FixtureRequest) -> None:
    """Every entry of ``KNOWN_DIVERGENCES`` still occurs in the responses."""
    names = [item.name for item in request.session.items]
    here = names.index(request.node.name)
    producers = (
        "test_the_collections_follow_ogc_common",
        "test_each_collection_follows_ogc_common",
    )
    if not all(
        any(name.startswith(f"{producer}[") for name in names[:here]) for producer in producers
    ):
        pytest.skip("the tests that meet the known divergences did not run before this one")

    assert set(KNOWN_DIVERGENCES) - SEEN == set()
