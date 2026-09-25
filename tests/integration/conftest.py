"""Shared fixtures for integration tests that require a real MongoDB.

Tests here are skipped automatically when no reachable MongoDB is
configured, so ``pytest`` still passes in environments without Docker. Point
at a real instance with ``CURSOR_MODEL_ROUTER_TEST_MONGO_URI`` (defaults to
the router's local compose service on port 27117).
"""

from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio
from pymongo import MongoClient
from pymongo.errors import PyMongoError

from cursor_model_router.common.config import RouterConfig
from cursor_model_router.common.constants import ConfigDefaults
from cursor_model_router.database.client import create_async_client, create_sync_client
from cursor_model_router.database.schema import initialize_schema

_TEST_MONGO_URI_ENV_VAR = "CURSOR_MODEL_ROUTER_TEST_MONGO_URI"


def _test_mongo_uri() -> str:
    return os.environ.get(_TEST_MONGO_URI_ENV_VAR, ConfigDefaults.DEFAULT_MONGO_URI)


def _is_reachable(uri: str) -> bool:
    try:
        client = MongoClient(uri, serverSelectionTimeoutMS=800, connectTimeoutMS=800)
        client.admin.command("ping")
        client.close()
        return True
    except PyMongoError:
        return False


requires_mongo = pytest.mark.skipif(
    not _is_reachable(_test_mongo_uri()),
    reason="No reachable MongoDB configured; start `docker compose up -d` or set "
    f"{_TEST_MONGO_URI_ENV_VAR}.",
)


@pytest.fixture
def mongo_uri() -> str:
    return _test_mongo_uri()


@pytest.fixture
def database_name() -> str:
    return f"cursor_model_router_test_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def router_config(mongo_uri, database_name, tmp_path):
    config = RouterConfig(mongo_uri=mongo_uri, database_name=database_name)
    config.home_dir = str(tmp_path / "home")
    return config


@pytest_asyncio.fixture
async def async_database(router_config):
    schema_client = create_sync_client(router_config)
    try:
        initialize_schema(schema_client, router_config.database_name)
    finally:
        schema_client.close()

    client = create_async_client(router_config)
    database = client[router_config.database_name]
    try:
        yield database
    finally:
        await client.drop_database(router_config.database_name)
        await client.close()


@pytest.fixture
def sync_client(router_config):
    client = create_sync_client(router_config)
    try:
        yield client
    finally:
        client.drop_database(router_config.database_name)
        client.close()
