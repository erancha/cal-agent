"""Classifies merchants with an OpenAI model answering in strict JSON-schema structured output."""

import json
import time
from collections.abc import Sequence

import openai

from calagent.adapters.classifiers.schema import REPLY_SCHEMA, answers_from
from calagent.adapters.model_costs import Usage, log_model_call
from calagent.domain.errors import ClassifierError
from calagent.domain.prompt import SYSTEM_PROMPT, merchant_lines
from calagent.ports.classifier import MerchantAnswer, MerchantQuery


class OpenAIClassifier:
    """Each answered call is logged as a "categorize" model call, a refused or empty reply
    included, since the provider bills it."""

    def __init__(self, model: str, api_key: str, client: openai.AsyncOpenAI | None = None) -> None:
        self._model = model
        if client is None:
            client = openai.AsyncOpenAI(api_key=api_key)
        self._client = client

    async def classify(self, queries: Sequence[MerchantQuery]) -> Sequence[MerchantAnswer]:
        started = time.perf_counter()
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
        assert completion.usage is not None, f"{self._model} answered without token usage"
        log_model_call(
            "categorize",
            f"openai:{self._model}",
            _billed(completion.usage),
            time.perf_counter() - started,
        )
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


def _billed(usage: openai.types.CompletionUsage) -> Usage:
    """OpenAI counts the cached prefix inside prompt_tokens, and reasoning inside
    completion_tokens; it charges nothing to write the cache."""
    details = usage.prompt_tokens_details
    cached = 0 if details is None or details.cached_tokens is None else details.cached_tokens
    return Usage(usage.prompt_tokens - cached, usage.completion_tokens, cached, 0)
