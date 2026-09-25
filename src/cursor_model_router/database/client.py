"""MongoDB client construction.

Two client flavors are exposed:

- :func:`create_sync_client` for the hook entry point, which is a short-lived
  process that must connect, write, and exit quickly.
- :func:`create_async_client` for the classification and verification
  workers, which run continuously and benefit from PyMongo's native
  asynchronous client for concurrent I/O.

Both honor the same short server-selection timeout so a missing or
unreachable MongoDB never hangs a Cursor hook; callers are expected to catch
:class:`pymongo.errors.PyMongoError` and fall back to the local spool.
"""

from __future__ import annotations

from pymongo import AsyncMongoClient, MongoClient

from cursor_model_router.common.config import RouterConfig
from cursor_model_router.common.constants import ConfigDefaults


def create_sync_client(config: RouterConfig) -> MongoClient:
    return MongoClient(
        config.mongo_uri,
        serverSelectionTimeoutMS=ConfigDefaults.MONGO_SERVER_SELECTION_TIMEOUT_MS,
        connectTimeoutMS=ConfigDefaults.MONGO_CONNECT_TIMEOUT_MS,
    )


def create_async_client(config: RouterConfig) -> AsyncMongoClient:
    return AsyncMongoClient(
        config.mongo_uri,
        serverSelectionTimeoutMS=ConfigDefaults.MONGO_SERVER_SELECTION_TIMEOUT_MS,
        connectTimeoutMS=ConfigDefaults.MONGO_CONNECT_TIMEOUT_MS,
    )
