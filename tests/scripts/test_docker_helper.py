"""docker-helper.sh --costs sums the model_call lines of the stack's logs by UTC day and by kind."""

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "lib" / "docker_helper.py"
_spec = importlib.util.spec_from_file_location("docker_helper", SCRIPT)
assert _spec is not None and _spec.loader is not None
docker_helper = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(docker_helper)

CALL = (
    '{{"event": "model_call", "kind": "{kind}", "model": "openai:gpt-5-mini", '
    '"input_tokens": {i}, "output_tokens": {o}, "cache_read_tokens": {r}, '
    '"cache_write_tokens": 0, "seconds": 1.2, "cost": {c}}}'
)
LINES = [
    "2026-11-20T23:59:58.100000000Z 2026-11-20T23:59:58Z [info     ] "
    + CALL.format(kind="turn", i=100, o=10, r=900, c=0.0005)
    + " [model_call]",
    "2026-11-21T00:00:03.000000000Z 2026-11-21 00:00:03.000 INFO 1 --- [main] model_call : "
    + CALL.format(kind="turn", i=200, o=20, r=0, c=0.001),
    "2026-11-21T08:15:00.000000000Z " + CALL.format(kind="retry turn", i=300, o=30, r=0, c=0.004),
    '2026-11-21T08:16:00.000000000Z [info     ] the reply mentions "model_call" in passing',
]


EXPECTED = """\
by day (UTC)
                   calls   tokens in  cache read cache write  tokens out    cost $
2026-11-20             1         100         900           0          10    0.0005
2026-11-21             2         500           0           0          50    0.0050

by kind
                   calls   tokens in  cache read cache write  tokens out    cost $
retry turn             1         300           0           0          30    0.0040
turn                   2         300         900           0          30    0.0015

total                  3         600         900           0          60    0.0055"""


def test_the_spend_is_summed_by_utc_day_by_kind_and_in_total() -> None:
    assert docker_helper.summarize(LINES) == EXPECTED
