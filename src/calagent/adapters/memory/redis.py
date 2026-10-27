"""Merchant memory in Redis, a hash per person (cal:merchants:<person>) without expiry; each field
is a memory key and its value the decision as JSON."""

import json
from collections.abc import Mapping, Sequence
from typing import cast

from redis.asyncio import Redis

from calagent.domain.merchants import Decision
from calagent.domain.rows import Confidence
from calagent.domain.taxonomy import require_category


def merchants_key(person: str) -> str:
    return f"cal:merchants:{person}"


class RedisMerchantMemory:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def get(self, person: str, keys: Sequence[str]) -> dict[str, Decision]:
        if not keys:
            return {}
        values = cast(list[str | None], await self._redis.hmget(merchants_key(person), keys))
        return {
            key: _decision(value)
            for key, value in zip(keys, values, strict=True)
            if value is not None
        }

    async def put(self, person: str, decisions: Mapping[str, Decision]) -> None:
        if not decisions:
            return
        await self._redis.hset(
            merchants_key(person),
            mapping={key: _json(decision) for key, decision in decisions.items()},
        )


def _json(decision: Decision) -> str:
    return json.dumps(
        {
            "merchant": decision.merchant,
            "category": decision.category,
            "confidence": decision.confidence.value,
        },
        ensure_ascii=False,
    )


def _decision(value: str) -> Decision:
    fields = json.loads(value)
    return Decision(
        fields["merchant"], require_category(fields["category"]), Confidence(fields["confidence"])
    )
