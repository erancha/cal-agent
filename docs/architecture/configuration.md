# Configuration

Every runtime setting is an environment variable, read once at startup; `.env` supplies them to the
scripts and to Docker, and a variable already exported in the calling shell wins over the same key
there. [.env.example](../../.env.example) is the one place each setting is explained: the required
ones are uncommented, every optional one is commented out at its default, and the test-only ones
are marked as such. A test holds `.env.example` to the settings the code reads, so no setting goes
unexplained.

A wrong required setting stops startup naming the variable, so a misconfigured agent never serves a
single request. Secrets, the model and the statements folder have no default for the same reason: a
guessed value would let the agent start and fail later, far from the cause. The same holds for the
files the settings name: a statements root that is not an existing directory (`STATEMENTS_DIR`)
stops startup naming the path, a static folder without the statements page (`STATIC_DIR`) stops
startup naming the file, and so, while authentication is required, does a callers file that is
missing, empty, or registers a blank field or two callers with one secret or one name. `start.sh`
creates the statements root before it launches, since Docker would otherwise create a missing
mount source owned by root, where the agent, running as the person who started it, cannot write
uploads. The image sets `STATIC_DIR` to where it installs the page, since the installed package
does not sit beside the repo's `static/` folder.

Four settings or values serve tests only. `AUTH_PUBLIC_KEY_FILE` replaces Google's published keys
with one PEM public key, so tests sign their own tokens; `CAL_TEST_SLOW_MS` makes every classifier
call wait first, so the multi-replica tests can act while a task works. Two more change what the
agent is:

- `LLM_MODEL=keyword` replaces the language model with a keyword table, so it needs no model or
  key ([categorizer.md](categorizer.md#providers)).
- `A2A_EXECUTOR=tck` replaces the card executor with the scenario executor the official A2A
  conformance suite scripts against, and turns authentication off
  ([testing.md](../testing.md#conformance)). Since it then serves every request without
  credentials, startup logs a warning naming it, and refuses it beside a shared Redis
  (`TASKS_REDIS_URL`) or an existing callers file, so it never runs inside a real deployment.
  `validate.sh --tck` is the one place that sets it.
