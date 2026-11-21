"""Classifies merchants with an Anthropic model forced to answer through one tool call."""

import time
from collections.abc import Sequence

import anthropic

from calagent.adapters.classifiers.schema import REPLY_SCHEMA, answers_from
from calagent.adapters.model_costs import Usage, log_model_call
from calagent.domain.errors import ClassifierError
from calagent.domain.prompt import SYSTEM_PROMPT, merchant_lines
from calagent.ports.classifier import MerchantAnswer, MerchantQuery

_TOOL_NAME = "answers"


class AnthropicClassifier:
    """Each answered call is logged as a "categorize" model call, a reply without answers
    included, since the provider bills it."""

    def __init__(
        self,
        model: str,
        api_key: str,
        max_tokens: int = 16384,
        client: anthropic.AsyncAnthropic | None = None,
    ) -> None:
        self._model = model
        self._max_tokens = max_tokens
        if client is None:
            client = anthropic.AsyncAnthropic(api_key=api_key)
        self._client = client

    async def classify(self, queries: Sequence[MerchantQuery]) -> Sequence[MerchantAnswer]:
        started = time.perf_counter()
        try:
            message = await self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": merchant_lines(queries)}],
                tools=[
                    {
                        "name": _TOOL_NAME,
                        "description": "Record the category of every merchant.",
                        "input_schema": REPLY_SCHEMA,
                        "strict": True,
                    }
                ],
                tool_choice={"type": "tool", "name": _TOOL_NAME},
            )
        except anthropic.APIError as error:
            raise ClassifierError(f"could not be asked for categories: {error}") from error
        log_model_call(
            "categorize",
            f"anthropic:{self._model}",
            _billed(message.usage),
            time.perf_counter() - started,
        )
        if message.stop_reason != "tool_use":
            raise ClassifierError(
                f"gave no categories: the model stopped with reason {message.stop_reason}"
            )
        for block in message.content:
            if block.type == "tool_use" and block.name == _TOOL_NAME:
                return answers_from(block.input)
        raise ClassifierError("gave no categories: the reply holds no answers tool call")


def _billed(usage: anthropic.types.Usage) -> Usage:
    """Anthropic counts input_tokens without the tokens read from or written to the cache, and
    leaves a cache count None when the request used no cache."""
    read = usage.cache_read_input_tokens
    written = usage.cache_creation_input_tokens
    return Usage(
        usage.input_tokens,
        usage.output_tokens,
        0 if read is None else read,
        0 if written is None else written,
    )
