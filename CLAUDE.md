# CLAUDE.md

A2A server for one skill, `monthly-transactions`, over Cal (כאל, Israel Credit Cards) PDF
statements: Python 3.14, FastAPI and the official `a2a-sdk` 1.x server, its routes and request
handler, with Redis shared by the replicas. README.md tells the story; `docs/a2a-contract.md`
describes how this agent implements the skill's contract, which the caller's repo owns;
`docs/architecture.md` and `docs/testing.md` hold the details. Do not change the artifact schema
or the taxonomy: they are the contract's, not this agent's.

## Layout and the layer rule

Package `calagent` in `src`: `platform → application → ports → domain`; `adapters` import only
`ports` and `domain`. `domain`, `ports` and `application` import no framework (a2a, fastapi,
starlette, redis, pdfplumber, anthropic, openai, httpx, yaml, structlog, jwt). `lint-imports`
enforces this from `pyproject.toml`. `platform/a2a` holds everything that touches the SDK.

## Scripts (scripts/, each prints usage with --help)

- `init-env.sh [--force]`: create `.env`; then set `AUTH_CLIENT_ID` and `LLM_API_KEY`.
- `register-caller.sh --name N --client-id C [--secret S] [--file F]`: register or replace an A2A
  caller in `allowed-callers.yaml` (gitignored); mints and prints the secret unless one is given.
- `start.sh [--host]`: Docker (default: Redis, two replicas, nginx edge on :8030) or one uvicorn
  process with everything in memory; stops before launching when access is required and no
  callers file exists.
- `docker-helper.sh --stop | --logs [-e] [service...] | --ps`.
- `test.sh [unit|it|all]`: ruff, mypy, lint-imports, pytest, then the shell tests in
  `scripts/tests/`; `all` (the default) and `it` include the integration tests, which need Docker.
- `validate.sh [--tck]`: the agent on :8031 with `LLM_MODEL=keyword` and a throwaway key in place
  of Google, proved by `scripts/validate/check_agent.py` (19 checks), then one boot per real
  provider on :8033; `--tck` runs the official A2A TCK on :8032 under `A2A_EXECUTOR=tck`.
- `lock.sh`: recompile `requirements.txt` inside the Dockerfile's Python image after editing the
  dependency list; the test venv installs under its pins.

## Facts that bite

- pdfplumber returns Hebrew in visual order: a Hebrew word's letters reversed, a cell's words left
  to right. Read cells by word positions through `adapters/pdf/words.py`, never from text lines.
- a2a-sdk 1.x types are protobuf: use `HasField`, `TaskState.Name(state)`, `get_data_parts`, not
  attribute checks or dicts.
- The SDK needs a `Task` event before any status: a new task's executor enqueues
  `new_task_from_user_message` first; a continue must not enqueue it again.
- The pause methods are `TaskUpdater.requires_input` and `requires_auth`; wire states are
  `TASK_STATE_*`, and the SDK ends the stream after an interrupted state.
- The SDK stores `TASK_STATE_FAILED` whenever the executor raises, so a request is refused in
  `platform/a2a/handler.py` before its task starts. Only `SendStreamingMessage` is served.
- Numbers are doubles on the wire (`796.0`): amounts are `Decimal` inside and become `float`
  only in `to_wire` (`domain/rows.py`). Numbers never come from the model.
- The SDK's task owner is the caller (the context user is the caller's name), not the person; the
  person is the `user` of the task's pause. Caller names are unique for that reason.
- A lease is owned per call (replica id and call id); the executor releases it in `finally`, the
  handler only when the SDK refuses a message before any event.
- `create_app` is a factory (`uvicorn calagent.platform.app:create_app --factory`); the module
  imports without any environment.
- Failure texts a person reads are predicates after the agent's name (`could not read ...`).
- The replica tests run on fixed port 18030, because the card advertises the URL the client calls.
- `tests/statements/` is tracked: real statements go in `statements/` or as `*.real.pdf`, never in
  `tests/statements/` under a plain name, and the anonymizer's `anonymize-*.json` mapping stays out
  of the repo. `tests/statements/2026-10.pdf` is the anonymized fixture every test runs on.
