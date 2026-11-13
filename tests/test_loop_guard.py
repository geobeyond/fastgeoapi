"""The loop guard catches the storage layer's synchronous calls, which obstore makes in Rust."""

import pytest


@pytest.mark.asyncio
async def test_a_synchronous_store_read_on_the_loop_is_caught(tmp_path):
    from blockbuster import BlockingError

    from app.provider.storage import load_store
    from tests.loop_guard import loop_guard

    (tmp_path / "object.bin").write_bytes(b"0123456789")
    store = load_store(str(tmp_path))
    with loop_guard(), pytest.raises(BlockingError):
        store.get_range("object.bin", 0, 4)


@pytest.mark.asyncio
async def test_the_async_twin_passes(tmp_path):
    from app.provider.storage import load_store
    from tests.loop_guard import loop_guard

    (tmp_path / "object.bin").write_bytes(b"0123456789")
    store = load_store(str(tmp_path))
    with loop_guard():
        assert await store.aget_range("object.bin", 0, 4) == b"0123"
