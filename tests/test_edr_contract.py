"""The contract a native EDR provider meets, and the configurations that break it.

The providers below are loaded by their dotted path, as a configuration names
them.
"""

import re

import pytest
from pygeoapi.provider.base import BaseProvider

from app.interfaces.providers import EdrCapabilities, EdrFormat, EdrLimits, NoDataFound
from app.pygeoapi.edr_contract import (
    validate_edr_contract_or_problem,
    validate_edr_provider_or_problem,
)
from app.pygeoapi.factory import ConfigValidationError, normalize_config
from tests.test_tiles_async_route import _collection, _config

CRS84 = "http://www.opengis.net/def/crs/OGC/1.3/CRS84"
WEB_MERCATOR = "http://www.opengis.net/def/crs/EPSG/0/3857"


class NoVersion(BaseProvider):
    """A native EDR provider without ``aget_version``."""

    native_async = True

    async def aretrieve_data(self, query):
        return None

    @property
    def limits(self):
        return None

    @property
    def capabilities(self):
        return None

    def close(self):
        """Nothing to release."""


def _build_capabilities_property(
    query_types=("position", "area"), crs=(CRS84,), default_crs=CRS84, formats=None
):
    """Build a ``capabilities`` property from the given declarations."""

    @property
    def capabilities(self):

        return EdrCapabilities(
            query_types=query_types,
            crs=crs,
            default_crs=default_crs,
            formats=(EdrFormat.COVERAGEJSON,) if formats is None else formats,
            parameters=(),
        )

    return capabilities


class Complete(BaseProvider):
    """A native EDR provider with every member."""

    native_async = True
    capabilities = _build_capabilities_property()

    async def aretrieve_data(self, query):

        return NoDataFound()

    async def aget_version(self, query):
        return None

    @property
    def limits(self):

        return EdrLimits(max_values=None)

    def close(self):
        """Nothing to release."""


class Cube(Complete):
    """A native EDR provider that offers the cube query."""

    capabilities = _build_capabilities_property(query_types=("cube",))


class DefaultOutsideCrs(Complete):
    """A native EDR provider whose default CRS is not among its CRSs."""

    capabilities = _build_capabilities_property(default_crs=WEB_MERCATOR)


class WithoutCrs84(Complete):
    """A native EDR provider that does not offer CRS84."""

    capabilities = _build_capabilities_property(crs=(WEB_MERCATOR,), default_crs=WEB_MERCATOR)


class PlainFormat(Complete):
    """A native EDR provider that declares its format as a bare string."""

    capabilities = _build_capabilities_property(formats=("CoverageJSON",))


def _definition(name: str, **extra) -> dict:
    return {"type": "edr", "name": name, "data": "unused", **extra}


def _normalize(name: str, **extra) -> None:

    normalize_config(_config({"grid": _collection("Grid", [_definition(name, **extra)])}))


def _refusal():

    return pytest.raises(ConfigValidationError, match=re.escape("resources.grid.providers.0"))


def test_a_native_edr_provider_missing_a_member_is_refused():

    name = "tests.test_edr_contract.NoVersion"
    message = f"{name} sets native_async but has no aget_version"

    with pytest.raises(ConfigValidationError, match=re.escape(message)) as error:
        _normalize(name)

    assert "resources.grid.providers.0" in str(error.value)


def test_a_complete_native_edr_provider_is_accepted():
    _normalize("tests.test_edr_contract.Complete")


def test_capabilities_must_offer_position_or_area_only():
    with _refusal() as error:
        _normalize("tests.test_edr_contract.Cube")

    assert "cube" in str(error.value)


def test_default_crs_must_be_among_the_crs():
    with _refusal() as error:
        _normalize("tests.test_edr_contract.DefaultOutsideCrs")

    assert WEB_MERCATOR in str(error.value)


def test_crs84_must_be_among_the_crs():
    with _refusal() as error:
        _normalize("tests.test_edr_contract.WithoutCrs84")

    assert "CRS84" in str(error.value)


def test_formats_must_be_edr_formats():
    with _refusal() as error:
        _normalize("tests.test_edr_contract.PlainFormat")

    assert "CoverageJSON" in str(error.value)


def test_a_non_native_edr_provider_is_not_checked():
    config = _config(
        {
            "grid": _collection(
                "Grid",
                [
                    {
                        "type": "edr",
                        "name": "xarray-edr",
                        "data": "unused",
                        "format": {"name": "zarr", "mimetype": "application/zip"},
                    }
                ],
            )
        }
    )

    assert validate_edr_contract_or_problem(config) is None
    assert validate_edr_provider_or_problem(config) is None


def test_the_covjson_conformance_classes_are_those_of_edr_1_0_and_1_1():
    assert EdrFormat.COVERAGEJSON.media_type == "application/prs.coverage+json"
    assert EdrFormat.COVERAGEJSON.conformance_classes == (
        "http://www.opengis.net/spec/ogcapi-edr-1/1.0/conf/covjson",
        "http://www.opengis.net/spec/ogcapi-edr-1/1.1/conf/covjson",
    )


def test_a_definition_with_an_unresolved_variable_is_not_built():
    config = _config(
        {
            "grid": _collection(
                "Grid",
                [_definition("tests.test_edr_contract.Cube", data="${GRID_DATA}")],
            )
        }
    )

    assert validate_edr_contract_or_problem(config) is None
    assert validate_edr_provider_or_problem(config) is None
