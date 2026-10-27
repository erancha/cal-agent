import pytest
from redis.asyncio import Redis

from calagent.adapters.memory.redis import RedisMerchantMemory, merchants_key
from calagent.domain.merchants import Decision
from calagent.domain.rows import Confidence

pytestmark = pytest.mark.integration

PIZZA = Decision("Pizza", "dining", Confidence.HIGH)
FUEL = Decision("Fuel", "transport", Confidence.MEDIUM)


async def test_decisions_round_trip_and_unknown_keys_are_absent(redis: Redis) -> None:
    memory = RedisMerchantMemory(redis)

    await memory.put("1000", {"k1": PIZZA, "k2": FUEL})

    assert await memory.get("1000", ["k1", "k2", "k3"]) == {"k1": PIZZA, "k2": FUEL}


async def test_each_person_has_their_own_memory(redis: Redis) -> None:
    memory = RedisMerchantMemory(redis)

    await memory.put("1000", {"k1": PIZZA})
    await memory.put("2000", {"k1": FUEL})

    assert await memory.get("1000", ["k1"]) == {"k1": PIZZA}
    assert await memory.get("2000", ["k1"]) == {"k1": FUEL}
    assert await memory.get("3000", ["k1"]) == {}


async def test_a_stored_category_outside_the_taxonomy_fails(redis: Redis) -> None:
    await redis.hset(
        merchants_key("1000"),
        "k1",
        '{"merchant": "Pizza", "category": "food", "confidence": "high"}',
    )

    with pytest.raises(ValueError, match="'food' is not a category"):
        await RedisMerchantMemory(redis).get("1000", ["k1"])
