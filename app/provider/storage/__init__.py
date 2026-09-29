"""Multi-provider object storage behind a structural Protocol (ADR-0003).

Re-exports the public surface: the contracts (``ObjectStore``,
``ObjectMeta``, ``ByteRanges``), the ``ObjectChangedError`` of a
conditional read, the ``RangeCache`` of byte ranges, the sync/async
``StorageBridge``, the obstore backend, the ``ObjectRanges`` adapter
and the ``load_store``/``split_source``/``is_remote`` factory helpers.
"""

from __future__ import annotations

from app.provider.storage.base import ObjectChangedError, ObjectMeta, ObjectStore
from app.provider.storage.bridge import StorageBridge
from app.provider.storage.cache import RangeCache
from app.provider.storage.factory import is_remote, load_store, split_source
from app.provider.storage.obstore_ import ObstoreStore
from app.provider.storage.ranges import ByteRanges, ObjectRanges, SingleFlightRanges

__all__ = [
    "ByteRanges",
    "ObjectChangedError",
    "ObjectMeta",
    "ObjectRanges",
    "ObjectStore",
    "ObstoreStore",
    "RangeCache",
    "SingleFlightRanges",
    "StorageBridge",
    "is_remote",
    "load_store",
    "split_source",
]
