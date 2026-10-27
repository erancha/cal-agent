"""Classifies merchants with an Anthropic model forced to answer through one tool call."""

from collections.abc import Sequence

import anthropic

from calagent.adapters.classifiers.schema import REPLY_SCHEMA, answers_from
from calagent.domain.errors import ClassifierError
from calagent.domain.prompt import SYSTEM_PROMPT, merchant_lines
from calagent.ports.classifier import MerchantAnswer, MerchantQuery

_TOOL_NAME = "answers"


class AnthropicClassifier:
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
        if message.stop_reason != "tool_use":
            raise ClassifierError(
                f"gave no categories: the model stopped with reason {message.stop_reason}"
            )
        for block in message.content:
            if block.type == "tool_use" and block.name == _TOOL_NAME:
                return answers_from(block.input)
        raise ClassifierError("gave no categories: the reply holds no answers tool call")
