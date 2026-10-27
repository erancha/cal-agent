"""A classifier that waits before answering, so tests can act while a task is still working."""

import asyncio
from collections.abc import Sequence

from calagent.ports.classifier import MerchantAnswer, MerchantClassifier, MerchantQuery


class SlowClassifier:
    def __init__(self, inner: MerchantClassifier, delay_seconds: float) -> None:
        self._inner = inner
        self._delay_seconds = delay_seconds

    async def classify(self, queries: Sequence[MerchantQuery]) -> Sequence[MerchantAnswer]:
        await asyncio.sleep(self._delay_seconds)
        return await self._inner.classify(queries)
