"""Chooses the classifier adapter named by the LLM_MODEL setting."""

from calagent.adapters.classifiers.anthropic import AnthropicClassifier
from calagent.adapters.classifiers.keyword import KeywordClassifier
from calagent.adapters.classifiers.openai import OpenAIClassifier
from calagent.ports.classifier import MerchantClassifier


def classifier_for(llm_model: str, api_key: str | None) -> MerchantClassifier:
    if llm_model == "keyword":
        return KeywordClassifier()
    provider, separator, model = llm_model.partition(":")
    if provider not in ("anthropic", "openai") or not separator or not model:
        raise ValueError(
            f"LLM_MODEL {llm_model!r} must be 'anthropic:<model>', 'openai:<model>' or 'keyword'"
        )
    if api_key is None:
        raise ValueError(f"LLM_API_KEY is required for LLM_MODEL {llm_model!r}")
    if provider == "anthropic":
        return AnthropicClassifier(model, api_key)
    return OpenAIClassifier(model, api_key)
