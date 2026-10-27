"""Fixtures shared by the integration tests: one Redis container per session, emptied per test."""

from collections.abc import AsyncIterator, Iterator

import pytest
from redis.asyncio import Redis
from testcontainers.community.redis import RedisContainer


@pytest.fixture(scope="session")
def redis_url() -> Iterator[str]:
    with RedisContainer("redis:7-alpine") as container:
        host, port = container.get_container_host_ip(), container.get_exposed_port(6379)
        yield f"redis://{host}:{port}/0"


@pytest.fixture
async def redis(redis_url: str) -> AsyncIterator[Redis]:
    client = Redis.from_url(redis_url, decode_responses=True)
    await client.flushdb()
    yield client
    await client.aclose()
