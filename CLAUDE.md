# CLAUDE.md

cal-agent: an A2A server for one skill, `monthly-transactions`, over Cal (כאל, Israel Credit
Cards) PDF statements, on Python 3.14, FastAPI and the official `a2a-sdk` 1.x server, with Redis
shared by the replicas. Layout, layers and parts: docs/architecture.md; how this agent implements
the skill's contract, which the caller's repo owns: docs/a2a-contract.md. Do not change the
artifact schema or the taxonomy: they are the contract's, not this agent's.

## Operations scripts (scripts/)

Every script sources `scripts/common.sh`, which exports the three settings files under
`scripts/lib/` before it calls Compose: the committed `stack-params.sh`, and the gitignored
`params.sh` and `secrets.sh`, each beside an `.example.sh` that documents its keys. A bare
`docker compose` call therefore has no settings. `.githooks/pre-commit` refuses a commit that
stages one of the gitignored files, a value of `secrets.sh`, or an address of `params.sh` other
than the license contact (`PUBLISHED_SETTINGS` of `lib/settings-guard.sh`). The callers
registry, `allowed-callers.yaml`, is gitignored and not checked by the hook.

- Compose hands each replica only the keys the agent reads, listed once in `docker-compose.yml`,
  and replaces the host forms of `STATEMENTS_DIR` and `A2A_CALLERS_FILE` with the container's
  paths. Host commands (pytest, uvicorn) run from the repo root, because the agent reads the
  settings files by their path from the working directory; tests pass `_env_file=None`.
- Nothing is bind-mounted but the local statements folder: the edge's `nginx/default.conf` is
  baked into its image, and Compose copies the callers registry into each replica from
  `A2A_CALLERS_YAML`, which `compose()` exports, labelled with its digest so a change recreates
  them. A registry change therefore takes a `deploy.sh` run, not a restart.
- The edge publishes `EDGE_HOST_PORT` (8030) on this machine's loopback interface and, on the
  instance, on its address: a caller in Docker reaches it through `host.docker.internal` on
  either.
- Package `calagent` in `src`: `platform → application → ports → domain`; `adapters` import only
  `ports` and `domain`. `domain`, `ports` and `application` import no framework (a2a, fastapi,
  starlette, redis, pdfplumber, anthropic, openai, httpx, yaml, structlog, jwt). `lint-imports`
  enforces this from `pyproject.toml`. `platform/a2a` holds everything that touches the SDK.
- pdfplumber returns Hebrew in visual order: a Hebrew word's letters reversed, a cell's words left
  to right. Read cells by word positions through `adapters/pdf/words.py`, never from text lines.
- a2a-sdk 1.x types are protobuf: use `HasField`, `TaskState.Name(state)`, `get_data_parts`, not
  attribute checks or dicts.
- The SDK needs a `Task` event before any status: a new task's executor enqueues
  `new_task_from_user_message` first; a continue must not enqueue it again.
- The pause methods are `TaskUpdater.requires_input` and `requires_auth`; wire states are
  `TASK_STATE_*`, and the SDK ends the stream after an interrupted state.
- The SDK stores `TASK_STATE_FAILED` whenever the executor raises, so a request is refused in
  `platform/a2a/handler.py` before its task starts. Only `SendStreamingMessage` is served; its
  SSE response sends a keep-alive comment every 15 seconds, which keeps a stream inside
  CloudFront's 30-second origin read timeout on the EC2 target.
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
- Before any AWS work, read this account's inventory, the
  `aws-account-inventory-<account ID>.md` under `/mnt/c/Projects/-- docs --/` that lists
  the stacks deployed there and which one hosts the instance.
- `test.sh [all|unit]` (alias `it` for `all`) — the whole quality gate: bash syntax check, ruff,
  mypy, lint-imports, pytest, the shell tests of `scripts/tests/`; `all` needs Docker.
- `init-env.sh [--force]` — creates each missing gitignored `scripts/lib/secrets.sh`,
  `params.sh` and `aws-config.sh` from its `.example.sh`; an existing file is kept unless
  `--force` is given.
- `deploy.sh` — runs `init-env.sh` first and stops on a list of every required setting still blank,
  or on a missing callers registry, then builds and runs Redis, two replicas and the edge in Docker
  Compose on :8030, and returns once the edge answers; `--ec2` does it on an EC2 instance, its own
  or another repo's as a guest (`EC2_HOST_STACK` of `params.sh`), behind its own CloudFront
  distribution (`template-ec2.yaml`, `docker-compose.ec2.yml`), in the account of the gitignored
  `lib/aws-config.sh`.
- `docker-helper.sh [--ec2]` — `--stop [--volumes]`, `--logs [-e] [service...]`, `--ps`,
  `--costs [--since <age>]` (model spend by day and kind, summed by `lib/docker_helper.py`, the
  same file in every Docker repo); `--ec2 --delete-stack` deletes this repo's EC2 stack.
- `lib/ec2.sh` — the EC2 target: the stack's deploy, SSH with an Instance Connect key, Compose
  against the instance's daemon. It, `template-ec2.yaml`, `lib/settings-guard.sh` (the checks
  behind the pre-commit hook) and `.githooks/pre-commit` are the same files in every Docker
  Compose repo, copied from loan-simulator byte for byte.
- `tools/register-caller.sh` — registers or replaces an A2A caller in `allowed-callers.yaml`.
- `tools/validate.sh [--tck]` — proves the agent from the client side; `--tck` adds the A2A TCK.
- `tools/anonymize-statement.py` — copies a statement PDF with the holder's details replaced.
- `tools/lock.sh` — recompiles `requirements.txt` inside the Dockerfile's Python image.
