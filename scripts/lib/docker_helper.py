"""Sums the stack's model_call log lines into the spend by UTC day and by kind of call. The logic
behind scripts/docker-helper.sh --costs, which pipes docker compose logs --timestamps into it.

The same file in every Docker repo. Each input line is the timestamp Docker recorded, in UTC, a
space, and the line a service logged, in whatever format that service writes; the call's JSON
object, which model_costs.py (or the Java agent's equivalent) logs per answered call, sits
somewhere in it and is read from its opening brace. A line that merely mentions model_call holds
no such object and does not count.
"""

import json
import sys
from collections import defaultdict
from dataclasses import dataclass

EVENT_PREFIX = '{"event": "model_call"'


@dataclass
class Total:
    """Calls, tokens and dollars summed over one group of model calls."""

    calls: int = 0
    input_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0

    def add(self, call: dict) -> None:
        self.calls += 1
        self.input_tokens += call["input_tokens"]
        self.cache_read_tokens += call["cache_read_tokens"]
        self.cache_write_tokens += call["cache_write_tokens"]
        self.output_tokens += call["output_tokens"]
        self.cost += call["cost"]


def model_calls(lines):
    """The (UTC day, call) of every model_call line among the logged lines."""
    decoder = json.JSONDecoder()
    for line in lines:
        timestamp, logged = line.split(" ", 1)
        start = logged.find(EVENT_PREFIX)
        if start != -1:
            call, _ = decoder.raw_decode(logged, start)
            yield timestamp[:10], call


def summarize(lines) -> str:
    by_day: dict[str, Total] = defaultdict(Total)
    by_kind: dict[str, Total] = defaultdict(Total)
    total = Total()
    for day, call in model_calls(lines):
        by_day[day].add(call)
        by_kind[call["kind"]].add(call)
        total.add(call)
    header = (
        f"{'':<16}{'calls':>8}{'tokens in':>12}{'cache read':>12}{'cache write':>12}"
        f"{'tokens out':>12}{'cost $':>10}"
    )

    def row(label: str, t: Total) -> str:
        return (
            f"{label:<16}{t.calls:>8}{t.input_tokens:>12}{t.cache_read_tokens:>12}"
            f"{t.cache_write_tokens:>12}{t.output_tokens:>12}{t.cost:>10.4f}"
        )

    out = ["by day (UTC)", header, *(row(d, by_day[d]) for d in sorted(by_day))]
    out += ["", "by kind", header, *(row(k, by_kind[k]) for k in sorted(by_kind))]
    out += ["", row("total", total)]
    return "\n".join(out)


if __name__ == "__main__":
    print(summarize(sys.stdin))
