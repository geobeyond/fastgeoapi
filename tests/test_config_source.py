"""One code path for local and cloud config: bytes → dict + etag."""

import pytest

from app.config.source import ConfigSourceError, aload_config_source, load_config_source

MINIMAL = b"server:\n  bind:\n    host: 0.0.0.0\nlogging:\n  level: ERROR\n"


@pytest.fixture
def config_path(tmp_path):
    target = tmp_path / "pygeoapi-config.yml"
    target.write_bytes(MINIMAL)
    return str(target)


def test_load_parses_yaml_and_carries_etag(config_path):
    document = load_config_source(config_path)
    assert document.config["server"]["bind"]["host"] == "0.0.0.0"
    assert document.etag
    assert document.source == config_path


@pytest.mark.asyncio
async def test_async_load_matches_sync(config_path):
    sync_doc = load_config_source(config_path)
    async_doc = await aload_config_source(config_path)
    assert async_doc.config == sync_doc.config
    assert async_doc.etag == sync_doc.etag


def test_invalid_yaml_raises_with_source_in_message(tmp_path):
    bad = tmp_path / "broken.yml"
    bad.write_bytes(b"server: [unclosed")
    with pytest.raises(ConfigSourceError, match=r"broken\.yml"):
        load_config_source(str(bad))


def test_non_mapping_yaml_is_rejected(tmp_path):
    scalar = tmp_path / "scalar.yml"
    scalar.write_bytes(b"- solo\n- una\n- lista\n")
    with pytest.raises(ConfigSourceError, match="mapping"):
        load_config_source(str(scalar))


def test_missing_source_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_config_source(str(tmp_path / "missing.yml"))
