"""Multi-provider object storage behind a structural Protocol (ADR-0003).

Re-exports the public surface: the contracts (``ObjectStore``,
``ObjectMeta``, ``ByteRanges``), the sync/async ``StorageBridge``, the
obstore backend, the ``ObjectRanges`` adapter and the
``load_store``/``split_source`` factory helpers.
"""

from __future__ import annotations

from app.provider.storage.base import ObjectMeta, ObjectStore
from app.provider.storage.bridge import StorageBridge
from app.provider.storage.factory import load_store, split_source
from app.provider.storage.obstore_ import ObstoreStore
from app.provider.storage.ranges import ByteRanges, ObjectRanges, SingleFlightRanges

__all__ = [
    "ByteRanges",
    "ObjectMeta",
    "ObjectRanges",
    "ObjectStore",
    "ObstoreStore",
    "SingleFlightRanges",
    "StorageBridge",
    "load_store",
    "split_source",
]
