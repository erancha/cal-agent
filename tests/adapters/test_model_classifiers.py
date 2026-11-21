import json
import logging
from collections.abc import Callable

import anthropic
import httpx2
import openai
import pytest

from calagent.adapters.classifiers.anthropic import AnthropicClassifier
from calagent.adapters.classifiers.factory import classifier_for
from calagent.adapters.classifiers.keyword import KeywordClassifier
from calagent.adapters.classifiers.openai import OpenAIClassifier
from calagent.adapters.classifiers.schema import ANSWERS_SCHEMA, answers_from
from calagent.adapters.model_costs import MODEL_CALL_LOGGER
from calagent.domain.errors import ClassifierError
from calagent.domain.prompt import SYSTEM_PROMPT
from calagent.ports.classifier import MerchantAnswer, MerchantQuery

QUERIES = [MerchantQuery("שופרסל דיל", "מזון"), MerchantQuery("TEMU.COM", "קניות")]
ANSWERS = [
    {"rawMerchant": "שופרסל דיל", "merchant": "שופרסל", "category": "groceries", "confidence": 0.9},
    {"rawMerchant": "TEMU.COM", "merchant": "Temu", "category": "shopping", "confidence": 0.7},
]
EXPECTED = [
    MerchantAnswer("שופרסל דיל", "שופרסל", "groceries", 0.9),
    MerchantAnswer("TEMU.COM", "Temu", "shopping", 0.7),
]
LINES = "שופרסל דיל [sector: מזון]\nTEMU.COM [sector: קניות]"


def _transport(
    reply: dict[str, object], status: int = 200
) -> tuple[httpx2.MockTransport, list[dict[str, object]]]:
    sent: list[dict[str, object]] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        sent.append(json.loads(request.content))
        return httpx2.Response(status, json=reply)

    return httpx2.MockTransport(handle), sent


def _anthropic(
    reply: dict[str, object], status: int = 200
) -> tuple[AnthropicClassifier, list[dict[str, object]]]:
    transport, sent = _transport(reply, status)
    client = anthropic.AsyncAnthropic(
        api_key="k", max_retries=0, http_client=httpx2.AsyncClient(transport=transport)
    )
    return AnthropicClassifier("claude-haiku-5-5", "k", client=client), sent


def _openai(
    reply: dict[str, object], status: int = 200
) -> tuple[OpenAIClassifier, list[dict[str, object]]]:
    transport, sent = _transport(reply, status)
    client = openai.AsyncOpenAI(
        api_key="k", max_retries=0, http_client=httpx2.AsyncClient(transport=transport)
    )
    return OpenAIClassifier("gpt-5-mini", "k", client=client), sent


def _anthropic_reply(
    content: list[dict[str, object]],
    stop_reason: str,
    usage: dict[str, int] | None = None,
) -> dict[str, object]:
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "m",
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": usage or {"input_tokens": 1, "output_tokens": 1},
    }


def _openai_reply(
    content: str | None,
    finish_reason: str,
    refusal: str | None = None,
    usage: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "id": "c1",
        "object": "chat.completion",
        "created": 0,
        "model": "m",
        "choices": [
            {
                "index": 0,
                "finish_reason": finish_reason,
                "message": {"role": "assistant", "content": content, "refusal": refusal},
            }
        ],
        "usage": usage or {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


async def test_anthropic_forces_the_answers_tool_and_parses_in_order() -> None:
    tool_use = {"type": "tool_use", "id": "t1", "name": "answers", "input": {"answers": ANSWERS}}
    classifier, sent = _anthropic(_anthropic_reply([tool_use], "tool_use"))

    assert await classifier.classify(QUERIES) == EXPECTED

    request = sent[0]
    assert request["system"] == SYSTEM_PROMPT
    assert request["messages"] == [{"role": "user", "content": LINES}]
    assert request["tool_choice"] == {"type": "tool", "name": "answers"}
    [tool] = request["tools"]  # type: ignore[misc]
    assert tool["strict"] is True
    assert tool["input_schema"]["properties"] == {"answers": ANSWERS_SCHEMA}


async def test_anthropic_without_a_tool_call_names_the_stop_reason() -> None:
    text = {"type": "text", "text": "no"}
    classifier, _ = _anthropic(_anthropic_reply([text], "max_tokens"))

    with pytest.raises(ClassifierError, match="max_tokens"):
        await classifier.classify(QUERIES)


async def test_anthropic_provider_error_is_a_classifier_error() -> None:
    error = {"type": "error", "error": {"type": "invalid_request_error", "message": "bad"}}
    classifier, _ = _anthropic(error, status=400)

    with pytest.raises(ClassifierError, match="bad"):
        await classifier.classify(QUERIES)


async def test_openai_asks_for_strict_schema_and_parses_in_order() -> None:
    classifier, sent = _openai(_openai_reply(json.dumps({"answers": ANSWERS}), "stop"))

    assert await classifier.classify(QUERIES) == EXPECTED

    request = sent[0]
    assert request["messages"] == [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": LINES},
    ]
    json_schema = request["response_format"]["json_schema"]  # type: ignore[index]
    assert json_schema["strict"] is True
    assert json_schema["schema"]["properties"] == {"answers": ANSWERS_SCHEMA}


async def test_openai_without_content_names_the_finish_reason() -> None:
    classifier, _ = _openai(_openai_reply(None, "content_filter"))

    with pytest.raises(ClassifierError, match="content_filter"):
        await classifier.classify(QUERIES)


async def test_openai_provider_error_is_a_classifier_error() -> None:
    classifier, _ = _openai({"error": {"message": "bad", "type": "invalid_request_error"}}, 400)

    with pytest.raises(ClassifierError, match="bad"):
        await classifier.classify(QUERIES)


def _every_object_is_strict(schema: object) -> bool:
    if isinstance(schema, dict):
        if schema.get("type") == "object" and (
            schema.get("additionalProperties") is not False
            or set(schema["properties"]) != set(schema["required"])
        ):
            return False
        return all(_every_object_is_strict(v) for v in schema.values())
    if isinstance(schema, list):
        return all(_every_object_is_strict(v) for v in schema)
    return True


def test_the_answer_schema_satisfies_strict_mode_at_every_level() -> None:
    assert _every_object_is_strict(ANSWERS_SCHEMA)


@pytest.mark.parametrize(
    ("setting", "adapter"),
    [
        ("anthropic:claude-haiku-5-5", AnthropicClassifier),
        ("openai:gpt-5-mini", OpenAIClassifier),
    ],
)
def test_factory_picks_the_provider_adapter(setting: str, adapter: Callable[..., object]) -> None:
    assert isinstance(classifier_for(setting, "key"), adapter)  # type: ignore[arg-type]


def test_factory_keyword_needs_no_key() -> None:
    assert isinstance(classifier_for("keyword", None), KeywordClassifier)


@pytest.mark.parametrize("setting", ["gemini:x", "anthropic", "anthropic:", "", "Keyword"])
def test_factory_rejects_other_forms_naming_the_setting(setting: str) -> None:
    with pytest.raises(ValueError, match="LLM_MODEL"):
        classifier_for(setting, "key")


@pytest.mark.parametrize("setting", ["anthropic:claude-x", "openai:gpt-x"])
def test_factory_provider_without_a_key_names_the_key(setting: str) -> None:
    with pytest.raises(ValueError, match="LLM_API_KEY is required for"):
        classifier_for(setting, None)


async def test_anthropic_truncated_reply_names_the_stop_reason_not_the_partial_input() -> None:
    partial = {"type": "tool_use", "id": "t1", "name": "answers", "input": {"answers": [{}]}}
    classifier, _ = _anthropic(_anthropic_reply([partial], "max_tokens"))

    with pytest.raises(ClassifierError, match="max_tokens"):
        await classifier.classify(QUERIES)


async def test_openai_truncated_reply_names_the_finish_reason() -> None:
    classifier, _ = _openai(_openai_reply('{"answers": [{"raw', "length"))

    with pytest.raises(ClassifierError, match="length"):
        await classifier.classify(QUERIES)


async def test_openai_refusal_carries_the_refusal_text() -> None:
    classifier, _ = _openai(_openai_reply(None, "stop", refusal="cannot help with that"))

    with pytest.raises(ClassifierError, match="cannot help with that"):
        await classifier.classify(QUERIES)


async def test_openai_non_json_content_is_a_classifier_error() -> None:
    classifier, _ = _openai(_openai_reply("not json", "stop"))

    with pytest.raises(ClassifierError, match="not JSON"):
        await classifier.classify(QUERIES)


@pytest.mark.parametrize(
    "reply",
    [
        [],
        {},
        {"answers": "text"},
        {"answers": [{"rawMerchant": "a"}]},
        {"answers": [{**ANSWERS[0], "confidence": "high"}]},
        {"answers": [{**ANSWERS[0], "merchant": None}]},
    ],
)
def test_a_reply_in_another_shape_is_a_classifier_error(reply: object) -> None:
    with pytest.raises(ClassifierError, match="unexpected shape"):
        answers_from(reply)


def test_factory_refuses_a_model_without_a_listed_price() -> None:
    with pytest.raises(ValueError, match="PRICE_PER_MILLION"):
        classifier_for("anthropic:claude-unlisted", "key")


def _logged_lines(caplog: pytest.LogCaptureFixture) -> list[dict[str, object]]:
    return [json.loads(r.getMessage()) for r in caplog.records if r.name == MODEL_CALL_LOGGER]


async def test_an_anthropic_call_logs_its_tokens_at_each_rate(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=MODEL_CALL_LOGGER)
    tool_use = {"type": "tool_use", "id": "t1", "name": "answers", "input": {"answers": ANSWERS}}
    usage = {
        "input_tokens": 200,
        "output_tokens": 50,
        "cache_read_input_tokens": 1000,
        "cache_creation_input_tokens": 300,
    }
    classifier, _ = _anthropic(_anthropic_reply([tool_use], "tool_use", usage))

    await classifier.classify(QUERIES)

    [line] = _logged_lines(caplog)
    assert line["kind"] == "categorize"
    assert line["model"] == "anthropic:claude-haiku-5-5"
    assert (line["input_tokens"], line["cache_read_tokens"], line["cache_write_tokens"]) == (
        200,
        1000,
        300,
    )
    assert line["cost"] == pytest.approx((200 * 0.10 + 50 * 0.50 + 1000 * 0.01 + 300 * 0.125) / 1e6)


async def test_an_anthropic_reply_without_answers_is_still_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=MODEL_CALL_LOGGER)
    classifier, _ = _anthropic(_anthropic_reply([{"type": "text", "text": "no"}], "max_tokens"))

    with pytest.raises(ClassifierError):
        await classifier.classify(QUERIES)

    assert len(_logged_lines(caplog)) == 1


async def test_an_openai_call_bills_its_cached_prefix_at_the_cached_price(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=MODEL_CALL_LOGGER)
    usage = {
        "prompt_tokens": 1000,
        "completion_tokens": 50,
        "total_tokens": 1050,
        "prompt_tokens_details": {"cached_tokens": 800},
    }
    classifier, _ = _openai(_openai_reply(json.dumps({"answers": ANSWERS}), "stop", usage=usage))

    await classifier.classify(QUERIES)

    [line] = _logged_lines(caplog)
    assert (line["kind"], line["model"]) == ("categorize", "openai:gpt-5-mini")
    assert (line["input_tokens"], line["cache_read_tokens"], line["cache_write_tokens"]) == (
        200,
        800,
        0,
    )
    assert line["cost"] == pytest.approx((200 * 0.25 + 50 * 2.00 + 800 * 0.025) / 1e6)
