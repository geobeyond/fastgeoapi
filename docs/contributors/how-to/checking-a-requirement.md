---
icon: material/check-decagram-outline
---

# :material-check-decagram-outline: Checking a requirement

A class listed in `/conformance` claims every requirement it carries. The
test module `tests/conformance/test_declared_is_verified.py` serves the
example and the demo configuration, reads the classes each one declares and
asks [ogcapi-registry](https://github.com/francbartoli/ogcapi-registry) for
their requirements. Each requirement must sit in one of the tables in
`tests/conformance/requirements.py`:

- `CHECKED` maps the requirement to the test that checks every part of it.
- `WAIVED` maps it to the reason no test does. A requirement checked only in
  part stays here, and the reason names the parts that are missing.

A declared class that ogcapi-registry does not catalogue, because its
standard is only a draft, goes in `DRAFTS` with the draft it comes from.

Requirements are named by their full URI, version included, with
`http://`:
`http://www.opengis.net/spec/ogcapi-maps-1/1.0/req/collection-map/desc-crs`.

## When the test fails

The failure lists the URIs that have no entry. They appear when a provider
or a configuration declares a new class, or when a new release of
ogcapi-registry catalogues more requirements. Two more tests keep the
tables up to date. An entry in `CHECKED` must name a test function that
exists, no URI may be both checked and waived, and every URI must be in the
catalogue.

## Checking a requirement

Read the parts of the requirement before writing its test:

```python
from ogcapi_registry import KNOWN_REQUIREMENTS

uri = "http://www.opengis.net/spec/ogcapi-maps-1/1.0/req/collection-map/desc-crs"
for part in KNOWN_REQUIREMENTS[uri].parts:
    print(part)
```

Write a test that checks all of them, then move the URI from `WAIVED` to
`CHECKED` with the pytest node id of the test:

```python
CHECKED: dict[str, str] = {
    "http://www.opengis.net/spec/ogcapi-maps-1/1.0/req/collection-map/desc-crs": (
        "tests/test_map_contract.py::test_the_collection_describes_the_crss_of_its_map"
    ),
}
```

The module is parsed, not imported, to find the test, so the node id needs
the path from the repository root and the function name. A parametrized id
such as `test_name[png]` is accepted.

## Waiving a requirement

Add the URI to `WAIVED` with its reason. `NOT_VERIFIED` is the reason for
a requirement nobody has checked yet; write a specific one when a test
covers part of it, or when the requirement does not apply and the class is
declared anyway.

## Running the tests

The module runs in the `conformance` lane with the schema tests:

```bash
uv run nox -s conformance
```

The demo reads remote GeoParquet data to build its OpenAPI document. When
that data cannot be read, its cases are skipped with the error as the
reason.
