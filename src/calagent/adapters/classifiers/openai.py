"""Classifies merchants with an OpenAI model answering in strict JSON-schema structured output."""

import json
from collections.abc import Sequence

import openai

from calagent.adapters.classifiers.schema import REPLY_SCHEMA, answers_from
from calagent.domain.errors import ClassifierError
from calagent.domain.prompt import SYSTEM_PROMPT, merchant_lines
from calagent.ports.classifier import MerchantAnswer, MerchantQuery


class OpenAIClassifier:
    def __init__(self, model: str, api_key: str, client: openai.AsyncOpenAI | None = None) -> None:
        self._model = model
        if client is None:
            client = openai.AsyncOpenAI(api_key=api_key)
        self._client = client

    async def classify(self, queries: Sequence[MerchantQuery]) -> Sequence[MerchantAnswer]:
        try:
            completion = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": merchant_lines(queries)},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": "answers", "strict": True, "schema": REPLY_SCHEMA},
                },
            )
        except openai.OpenAIError as error:
            raise ClassifierError(f"could not be asked for categories: {error}") from error
        choice = completion.choices[0]
        if choice.message.refusal is not None:
            raise ClassifierError(f"was refused by the model: {choice.message.refusal}")
        if choice.finish_reason != "stop" or choice.message.content is None:
            raise ClassifierError(
                f"gave no categories: the model stopped with reason {choice.finish_reason}"
            )
        try:
            reply = json.loads(choice.message.content)
        except json.JSONDecodeError as error:
            raise ClassifierError(f"returned categories that are not JSON: {error}") from error
        return answers_from(reply)
