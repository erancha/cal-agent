import pytest
from redis.asyncio import Redis

from calagent.adapters.tasks.redis_lease import RedisLease

pytestmark = pytest.mark.integration


async def test_only_one_owner_holds_a_lease(redis: Redis) -> None:
    lease = RedisLease(redis, 60)

    assert await lease.acquire("t1", "a")
    assert not await lease.acquire("t1", "b")
    assert not await lease.acquire("t1", "a")
    assert await lease.owner_of("t1") == "a"
    assert 0 < await redis.pttl("cal:lease:t1") <= 60_000


async def test_only_the_owner_renews_or_releases(redis: Redis) -> None:
    lease = RedisLease(redis, 60)
    await lease.acquire("t1", "a")

    assert not await lease.renew("t1", "b")
    await lease.release("t1", "b")
    assert await lease.owner_of("t1") == "a"
    assert await lease.renew("t1", "a")
    await lease.release("t1", "a")

    assert await lease.owner_of("t1") is None
    assert not await lease.renew("t1", "a")
