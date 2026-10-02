"""The HTTP cache policy: ETags, Cache-Control and the If-None-Match comparison.

``app.*`` is imported at the top of this module, nowhere else; the live
settings object is looked up with ``importlib`` where a test changes it.
"""

import importlib
from types import SimpleNamespace

import pytest

from app.config.app import DevConfig, ProdConfig
from app.pygeoapi.api_async.caching import (
    HttpCache,
    default_http_cache,
    not_modified,
    sources_digest,
)

POLICY = HttpCache(max_age=300, protected=False, code="code-1")
BASE = ("roads", "tile", "v1", {"z": 1, "x": 2, "y": 3})
ETAG = '"abc"'


def test_the_same_input_gives_the_same_etag():
    assert POLICY.etag(*BASE) == POLICY.etag(*BASE)


def test_the_policy_itself_does_not_count_in_the_etag():
    other = HttpCache(max_age=60, protected=True, code="code-1")

    assert other.etag(*BASE) == POLICY.etag(*BASE)


@pytest.mark.parametrize(
    "changed",
    [
        ("places", "tile", "v1", {"z": 1, "x": 2, "y": 3}),
        ("roads", "map", "v1", {"z": 1, "x": 2, "y": 3}),
        ("roads", "tile", "v2", {"z": 1, "x": 2, "y": 3}),
        ("roads", "tile", "v1", {"z": 1, "x": 2, "y": 4}),
    ],
    ids=["dataset", "kind", "version", "arguments"],
)
def test_every_ingredient_changes_the_etag(changed):
    assert POLICY.etag(*changed) != POLICY.etag(*BASE)


def test_another_code_changes_the_etag():
    newer = HttpCache(max_age=300, protected=False, code="code-2")

    assert newer.etag(*BASE) != POLICY.etag(*BASE)


def test_the_order_of_the_arguments_does_not_count():
    assert POLICY.etag("roads", "tile", "v1", {"y": 3, "x": 2, "z": 1}) == POLICY.etag(*BASE)


def test_an_etag_is_a_quoted_strong_validator():
    etag = POLICY.etag(*BASE)

    assert etag.startswith('"') and etag.endswith('"')
    assert not etag.startswith("W/")


@pytest.mark.parametrize("header", ['"abc"', 'W/"abc"', '"other", "abc"', '"other",W/"abc"', " * "])
def test_if_none_match_naming_the_etag_is_not_modified(header):
    assert not_modified(header, ETAG)


@pytest.mark.parametrize("header", [None, "", '"other"', "abc", '"abcd"'])
def test_if_none_match_naming_another_etag_is_modified(header):
    assert not not_modified(header, ETAG)


def test_a_public_instance_lets_any_cache_keep_the_answer():
    assert POLICY.cache_control() == "public, max-age=300"


def test_a_protected_instance_lets_only_the_browser_keep_it():
    protected = HttpCache(max_age=300, protected=True, code="code-1")

    assert protected.cache_control() == "private, max-age=300"


def test_the_headers_name_the_etag_the_policy_and_what_the_answer_varies_on():
    assert POLICY.headers(ETAG) == {
        "ETag": ETAG,
        "Cache-Control": "public, max-age=300",
        "Vary": "Accept, Accept-Encoding",
    }


def test_a_max_age_of_zero_turns_the_cache_off():
    assert POLICY.enabled is True
    assert HttpCache(max_age=0, protected=False, code="code-1").enabled is False


def _settings(**values):
    defaults = {
        "FASTGEOAPI_HTTP_MAX_AGE_SECONDS": 300,
        "OPA_ENABLED": None,
        "JWKS_ENABLED": None,
        "API_KEY_ENABLED": None,
    }
    return SimpleNamespace(**{**defaults, **values})


def test_the_settings_give_the_max_age_and_a_public_policy():
    policy = HttpCache.from_settings(_settings(FASTGEOAPI_HTTP_MAX_AGE_SECONDS=120))

    assert (policy.max_age, policy.protected) == (120, False)


@pytest.mark.parametrize("switch", ["OPA_ENABLED", "JWKS_ENABLED", "API_KEY_ENABLED"])
def test_any_authentication_makes_the_policy_private(switch):
    assert HttpCache.from_settings(_settings(**{switch: True})).protected is True


def test_the_default_policy_reads_the_settings_of_the_process(monkeypatch):
    settings = importlib.import_module("app.config.app").configuration
    monkeypatch.setattr(settings, "FASTGEOAPI_HTTP_MAX_AGE_SECONDS", 120)
    monkeypatch.setattr(settings, "JWKS_ENABLED", True)

    assert default_http_cache().cache_control() == "private, max-age=120"


def test_the_max_age_defaults_to_five_minutes(monkeypatch):
    monkeypatch.delenv("DEV_FASTGEOAPI_HTTP_MAX_AGE_SECONDS", raising=False)
    monkeypatch.delenv("PROD_FASTGEOAPI_HTTP_MAX_AGE_SECONDS", raising=False)

    assert DevConfig().FASTGEOAPI_HTTP_MAX_AGE_SECONDS == 300
    assert ProdConfig().FASTGEOAPI_HTTP_MAX_AGE_SECONDS == 300


def test_the_environment_sets_the_max_age(monkeypatch):
    monkeypatch.setenv("DEV_FASTGEOAPI_HTTP_MAX_AGE_SECONDS", "0")

    assert DevConfig().FASTGEOAPI_HTTP_MAX_AGE_SECONDS == 0


def test_the_code_digest_follows_the_sources_and_nothing_else(tmp_path):
    package = tmp_path / "pkg"
    (package / "__pycache__").mkdir(parents=True)
    module = package / "module.py"
    module.write_text("A = 1\n")
    first = sources_digest(tmp_path)

    (package / "__pycache__" / "module.cpython-312.pyc").write_bytes(b"compiled")
    (package / "notes.txt").write_text("not code")
    unchanged = sources_digest(tmp_path)
    module.write_text("A = 2\n")

    assert unchanged == first
    assert sources_digest(tmp_path) != first
