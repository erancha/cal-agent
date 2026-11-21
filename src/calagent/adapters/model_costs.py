"""What one model call costs, and the model_call log line that records it.

The same file in every Python Docker repo, so the price table and the line's shape are one
definition that scripts/lib/docker_helper.py, behind docker-helper.sh --costs, sums.

Core building blocks:
- PRICE_PER_MILLION: the listed prices of every model the repos run
- Usage / call_cost: the tokens of one call at each rate, and the dollars they cost
- require_price: refuses a provider:model whose prices are not listed, before a client is built
- log_model_call: one JSON line per answered call on the MODEL_CALL_LOGGER logger
"""

import json
import logging
from dataclasses import dataclass

MODEL_CALL_LOGGER = "model_call"

# Dollars per million input, output, cache-read and cache-write tokens, keyed by the model id of a
# provider:model setting, from the providers' price pages on 2026-11-21. Anthropic prices a cache
# write, for an entry that lives five minutes, at 1.25 times the input price; OpenAI charges
# nothing to write. Claude Haiku 5.5's prices hold for prompts up to 100K tokens, and the GPT-6
# models' for prompts up to 272K; a longer prompt is billed higher than its line says.
PRICE_PER_MILLION = {
    "claude-opus-5": (5.0, 25.0, 0.5, 6.25),
    "claude-sonnet-4-6": (3.0, 15.0, 0.3, 3.75),
    "claude-haiku-5-5": (0.10, 0.50, 0.01, 0.125),
    "claude-haiku-4-5-20251001": (1.0, 5.0, 0.1, 1.25),
    "gpt-6.2-astra": (8.0, 40.0, 0.4, 0.0),
    "gpt-5-mini": (0.25, 2.0, 0.025, 0.0),
    "gpt-5-nano": (0.05, 0.40, 0.005, 0.0),
}


@dataclass(frozen=True)
class Usage:
    """Billed tokens of one call; reasoning tokens count as output. input_tokens are the ones
    billed at the full input price, so they leave out the tokens read from or written to the
    prompt cache."""

    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int


def model_id(spec: str) -> str:
    """The model id of a provider:model setting, or of a bare model id."""
    return spec.rpartition(":")[2]


def require_price(spec: str) -> None:
    if model_id(spec) not in PRICE_PER_MILLION:
        raise ValueError(
            f"{spec!r} has no listed price; add its prices per million tokens to "
            "PRICE_PER_MILLION in model_costs.py"
        )


def call_cost(spec: str, usage: Usage) -> float:
    per_input, per_output, per_read, per_write = PRICE_PER_MILLION[model_id(spec)]
    dollars = (
        usage.input_tokens * per_input
        + usage.output_tokens * per_output
        + usage.cache_read_tokens * per_read
        + usage.cache_write_tokens * per_write
    )
    return dollars / 1_000_000


def log_model_call(kind: str, spec: str, usage: Usage, seconds: float) -> None:
    """kind names what the call was for, as the --costs table groups it."""
    line = {
        "event": "model_call",
        "kind": kind,
        "model": spec,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cache_read_tokens": usage.cache_read_tokens,
        "cache_write_tokens": usage.cache_write_tokens,
        "seconds": round(seconds, 2),
        "cost": call_cost(spec, usage),
    }
    logging.getLogger(MODEL_CALL_LOGGER).info(json.dumps(line))
