"""The limits and the CRS the document publishes are those the route applies."""

MAP = "/collections/under_test/map"
OUTSIDE = "http://www.opengis.net/def/crs/EPSG/0/32633"


def _parameters(client) -> tuple[dict, dict[str, dict]]:
    document = client.get("/openapi", params={"f": "json"}).json()
    parameters = document["paths"][MAP]["get"]["parameters"]
    return document, {p["name"]: p["schema"] for p in parameters if "name" in p}


def test_the_published_maximum_is_the_one_applied(contract):
    from app.pygeoapi.map_limits import get_default_map_ceiling

    document, schemas = _parameters(contract.client)
    width, height = schemas["width"]["maximum"], schemas["height"]["maximum"]
    ceiling = get_default_map_ceiling()

    def status(**size):
        return contract.client.get(MAP, params={"width": 16, "height": 16, **size}).status_code

    assert (status(width=width), status(width=width + 1)) == (200, 413)
    assert (status(height=height), status(height=height + 1)) == (200, 413)
    assert document["info"]["x-OGC-limits"]["maps"] == {
        "maxWidth": ceiling.max_width,
        "maxHeight": ceiling.max_height,
    }


def test_every_published_crs_is_drawn(contract):
    _, schemas = _parameters(contract.client)

    for crs in schemas["crs"]["enum"]:
        response = contract.client.get(MAP, params={"crs": crs, "width": 16, "height": 16})
        assert response.status_code == 200, (crs, response.text[:200])


def test_a_crs_not_published_is_refused(contract):
    _, schemas = _parameters(contract.client)
    assert OUTSIDE not in schemas["crs"]["enum"]

    response = contract.client.get(MAP, params={"crs": OUTSIDE, "width": 16, "height": 16})

    assert response.status_code == 400, response.text[:200]
