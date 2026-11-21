# Development & deployment

This document details the local setup, the tests and the scripts behind the
[README](../README.md)'s Getting started and Scripts sections; [Architecture](architecture.md)
describes what the scripts run. Each script's header comment is its full documentation, and
`--help` prints it.

**Contents:** [Working copy location](#working-copy-location) · [Configuration](#configuration) ·
[Backend tests](#backend-tests) · [Deployment scripts (scripts/)](#deployment-scripts-scripts) ·
[The EC2 stack](#the-ec2-stack) · [Registering a caller](#registering-a-caller) ·
[Loading statements](#loading-statements) ·
[Running the agent on the host](#running-the-agent-on-the-host) · [Gotchas](#gotchas)

## Working copy location

Keep the checkout on the WSL ext4 filesystem (`~/projects/python/cal-agent`) rather than under
`/mnt/c`. WSL reaches Windows drives through a file-sharing protocol that makes every file open a
round trip to the Windows side, and the virtualenv install and the test runs open thousands of
files.

## Configuration

`./scripts/init-env.sh` creates the gitignored `secrets.sh`, `params.sh` and `aws-config.sh`
under `scripts/lib/` from [secrets.example.sh](../scripts/lib/secrets.example.sh),
[params.example.sh](../scripts/lib/params.example.sh) and
[aws-config.example.sh](../scripts/lib/aws-config.example.sh), keeping a file that already
exists; each setting's comment says what it holds and whether it is required. `deploy.sh` runs
it first on every run, and stops with a list of every setting it needs that is still blank.

- `secrets.sh` — `LLM_API_KEY`, the Anthropic or OpenAI key of the model `LLM_MODEL` names.
- `params.sh` — this deployment's own settings that are no secret: `LLM_MODEL` as
  `provider:model` (`anthropic:claude-haiku-5-5` as created; `keyword` replaces the model with a
  built-in keyword table that needs no key, as the tests and `tools/validate.sh` run),
  `AUTH_CLIENT_ID`, the client id of the agent's own Google OAuth client
  ([Sign-in](sign-in.md) sets it up), and the license contact.
- `aws-config.sh` — the access key pair and region of the AWS account `deploy.sh --ec2`
  deploys to; a machine that deploys only locally leaves it unfilled.

Every other setting is committed in [stack-params.sh](../scripts/lib/stack-params.sh): the
edge's port, the URL the card advertises, the statements folder, the EC2 stack's names and every
optional setting at its default. Each setting is explained once, in `stack-params.sh` or in the
`.example.sh` beside a gitignored file: the required ones are uncommented, every optional one is
commented out at its default, and the test-only ones are marked as such.
`tests/test_settings_files.py` holds the files to the settings the code reads, so no setting goes
unexplained, and `tests/test_compose.py` holds the replicas' environment to the same list.

`AGENT_URL` is `http://host.docker.internal:8030` as shipped,
since a caller in Docker on this machine, such as the home finance agent, reaches the edge there;
`localhost` would be the caller's own container. On the EC2 instance the card advertises the
stack's CloudFront address instead. An edit to any of the three files takes a `deploy.sh` run.

A script that loads a settings file first stops if git would track it, or a tracked file holds
one of its secrets or email addresses, the license contact of `params.sh` excepted. It also
sets `core.hooksPath` to `.githooks`, whose `pre-commit` hook makes the same check on every
commit's staged changes. The callers registry, `allowed-callers.yaml`, is gitignored on its own.

The agent reads every setting once, at startup. The scripts export the three files into their
shell before calling Compose, so a bare `docker compose` call has no settings. Compose hands each
replica only the keys the agent reads, listed in `docker-compose.yml`. The files hold the host
forms of `STATEMENTS_DIR` and `A2A_CALLERS_FILE`; Compose replaces both with the paths inside the
container. Host commands (pytest, uvicorn) run from the repo root, because the agent reads the
settings files by their path from the working directory.

A wrong required setting stops startup naming the variable, so a misconfigured agent never serves a
single request. Secrets, the model and the statements folder have no default for the same reason: a
guessed value would let the agent start and fail later, far from the cause. The same holds for the
files the settings name: a statements root that is not an existing directory (`STATEMENTS_DIR`)
stops startup naming the path, a static folder without the statements page (`STATIC_DIR`) stops
startup naming the file, and so, while authentication is required, does a callers file that is
missing, empty, or registers a blank field or two callers with one secret or one name. `deploy.sh`
creates the statements root before it starts the local stack, since Docker would otherwise create a
missing mount source owned by root, where the agent, running as the person who started it, cannot
write uploads. On the EC2 instance the statements root is the `cal_statements` volume instead, which
starts as a copy of the image's empty `/statements` folder, owned by the agent's user. The image
sets `STATIC_DIR` to where it installs the page, since the installed package does not sit beside the
repo's `static/` folder.

Four settings or values serve tests only. `AUTH_PUBLIC_KEY_FILE` replaces Google's published keys
with one PEM public key, so tests sign their own tokens; `CAL_TEST_SLOW_MS` makes every classifier
call wait first, so the multi-replica tests can act while a task works. Two more change what the
agent is:

- `LLM_MODEL=keyword` replaces the language model with a keyword table, so it needs no model or
  key ([Categorizer](architecture/categorizer.md#providers)).
- `A2A_EXECUTOR=tck` replaces the card executor with the scenario executor the official A2A
  conformance suite scripts against, and turns authentication off
  ([Testing](testing.md#conformance)). Since it then serves every request without
  credentials, startup logs a warning naming it, and refuses it beside a shared Redis
  (`TASKS_REDIS_URL`) or an existing callers file, so it never runs inside a real deployment.
  `tools/validate.sh --tck` is the one place that sets it.

## Backend tests

[`test.sh`](../scripts/test.sh) is the whole quality gate: the scripts' syntax check, ruff lint
and format check, mypy, `lint-imports` (the layer rule of `pyproject.toml`), pytest, then the
shell tests of `scripts/tests/`. With no argument, `all` or `it` it includes the integration
tests, which start Redis through Testcontainers and so need Docker; `unit` leaves them out. It
needs Python 3.14, and creates `.venv` on its first run with the runtime dependencies at the pins
of `requirements.txt`, the ones the image installs.

[`tools/validate.sh`](../scripts/tools/validate.sh) runs the agent on port 8031 and proves it
from the client side as a registered caller; `--tck` also runs the official A2A conformance
suite. It needs openssl besides Python. The GitHub Actions workflow `.github/workflows/ci.yml`
runs `test.sh all` and `tools/validate.sh`. [Testing](testing.md) states what each layer covers.

## Deployment scripts (`scripts/`)

Docker with Compose runs the stack; `deploy.sh` and `docker-helper.sh` stop when it is not
reachable.

- [`deploy.sh`](../scripts/deploy.sh) — builds the images, starts Redis, two replicas of the
  agent and the nginx edge on http://localhost:8030, and returns once the edge answers. It stops
  first while no caller is registered (below), and ends with the values a caller's operator
  records: this agent's name, `cal`, the advertised URL and the statements page's URL.
- `deploy.sh --ec2` — deploys to an EC2 instance in the account of `aws-config.sh`, and needs the
  AWS CLI, `ssh` and `curl`; [The EC2 stack](#the-ec2-stack) has what it creates and runs there.
  It prints the CloudFront address to register with Google
  ([Sign-in](sign-in.md#setting-up-google)) and the values a caller's operator records there.
- [`docker-helper.sh`](../scripts/docker-helper.sh) — `--stop [--volumes]`,
  `--logs [-e] [service...]`, `--ps` or `--costs [--since <age>]` for the stack; `--volumes`
  also drops the paused tasks and the merchant memory held in the Redis volume, and on the
  instance the statements. `--costs` sums the model calls of the running containers' logs by UTC
  day and by kind of call (a batch of merchants to categorize), in dollars at the prices of
  `src/calagent/adapters/model_costs.py`. With `--ec2` as its first argument it acts on the
  instance, and `--ec2 --delete-stack` deletes this repo's EC2 stack: its port on the instance
  and its distribution.
- [`test.sh`](../scripts/test.sh) — the quality gate, above.
- [`init-env.sh`](../scripts/init-env.sh) — creates the settings files, above; `--force`
  replaces existing ones, hand-filled keys included.
- `tools/` — hands-on tools: [`register-caller.sh`](../scripts/tools/register-caller.sh)
  (registers an A2A caller, below), [`validate.sh`](../scripts/tools/validate.sh) (the
  client-side proof and the conformance suite, above),
  [`anonymize-statement.py`](../scripts/tools/anonymize-statement.py) (copies a statement PDF
  with the holder's private details replaced, to use as a test fixture) and
  [`lock.sh`](../scripts/tools/lock.sh) (recompiles `requirements.txt` from `pyproject.toml`
  inside the Dockerfile's Python image; run it after editing the dependency list).
  [`tools/README.md`](../scripts/tools/README.md) lists them.

`scripts/common.sh` holds what the scripts share: the repo paths, the help printer, the loader
of the settings files, Compose access, the callers-registry and statements-folder checks, the
hand-over lines and the virtualenv setup. `lib/settings-guard.sh` keeps the gitignored files'
values out of git, and `lib/ec2.sh` holds the EC2 target: the stack's deploy, the SSH connection
with an EC2 Instance Connect key, and Compose pointed at the instance's Docker daemon. Both, and
`template-ec2.yaml`, are the same files in every Docker Compose repo of the demo.

The IAM user of `aws-config.sh` needs to create and delete the stack's resources
(CloudFormation, a rule in the host's security group, CloudFront distributions), to update the
host stack's SSH rule, and `ec2-instance-connect:SendSSHPublicKey` for the SSH connection. No IAM
user has these by default; an administrator has them all.

## The EC2 stack

`./scripts/deploy.sh --ec2` runs the same Compose stack on an EC2 instance, as a stack of the shared
CloudFormation template, [`template-ec2.yaml`](../scripts/template-ec2.yaml), that hosts the
instance or joins another Docker Compose repo's as a guest: it opens port 8030 to CloudFront's
servers and adds a CloudFront distribution whose https address is the way in, and which the card
advertises there ([ADR 0007](adr/0007-guest-on-loan-simulators-ec2-instance.md)). The images are
built on the deployer's machine for ARM and loaded into the instance's Docker daemon over SSH, and
Compose runs there against that daemon, so nothing is bind-mounted from the deployer's machine: the
edge's configuration is part of its image, Compose copies the callers registry into each replica,
and on the instance the statements live in the `cal_statements` volume. `docker-compose.ec2.yml`
holds what differs there.

The stack is a host, with an instance of its own, while `EC2_HOST_STACK` of `params.sh` is blank.
Set to another Docker Compose repo's host stack, it is a guest on that instance, which is deployed
first from its repo; `aws-config.sh` then names that stack's account and region, since a guest's
stacks import the host stack's exports
([ADR 0008](adr/0008-any-docker-repo-can-host-the-instance.md)). The git branch selects the
stacks: `main` deploys `cal-agent`, any other branch `cal-agent-fb`, a guest on the host's `-fb`
instance; an exported `STACK_NAME` wins. Every deploy, host or guest, also makes sure the instance
has a 1 GB swap file (`prepare_ec2_host` in `lib/ec2.sh`), so a burst beyond the instance's 2 GB
of memory slows the stacks instead of killing a container.

## Registering a caller

A program that calls the A2A skill is registered by its name and the Google client id of its own
sign-in, whose tokens it forwards; its operator hands you that id. The agent refuses to start
without a caller, and `deploy.sh` stops early to say so:

```bash
./scripts/tools/register-caller.sh --name <caller> --client-id <the caller's client id>
```

The registration prints the values the caller's operator records: this agent's name, its A2A
URL, its statements page URL and the secret, shown once. Hand them over; the secret is the same
for the local stack and the EC2 one, and `deploy.sh --ec2` prints the instance's URLs. The
replicas receive the registry when Compose creates them, so run `deploy.sh` (or `--ec2`) after a
change: a changed registry recreates them.

## Loading statements

Download each monthly statement PDF from the Cal site and load it on the statements page,
http://localhost:8030/statements.html on this machine or `<CloudFront address>/statements.html`
on the EC2 instance: sign in with your Google account, and the page lists the statements you
loaded, deletes one on request and stores each upload under its billing month whatever the file
is called, in a folder of your own. On this machine that folder is under `statements/` (git
ignores it); on the instance it is in the `cal_statements` volume, and the page is the only way
in. A statement's billing month is the month the card is charged, printed in its title: the
statement charged on 2 October 2026 is stored as `2026-10.pdf` and answers a request for
`2026-10`. The page only loads files; everything about the month's spending happens in the
caller.

## Running the agent on the host

For fast restarts and a debugger, run one agent process from the venv instead of the stack, with
its tasks and the merchant memory in its own memory and no edge. Run it from the repo root, so it
reads the settings files, once `./scripts/test.sh unit` has created `.venv` and
`./scripts/deploy.sh` has created the statements folder:

```bash
./scripts/docker-helper.sh --stop   # the stack's edge holds port 8030
.venv/bin/uvicorn calagent.platform.app:create_app --factory --host 0.0.0.0 --port 8030
```

## Gotchas

- The scripts source the settings files, so a key a file sets replaces a variable of the same
  name exported in the calling shell; a key left commented out does not. An agent started on the
  host reads the files the other way round: a variable of its environment wins.
- The replicas read `allowed-callers.yaml` when they start, so registering or removing a caller
  takes a `deploy.sh` run.
- The replica tests run on the fixed port 18030, because the card advertises the URL the client
  calls.
- `tests/statements/` is tracked: real statements go in `statements/` or as `*.real.pdf`, never
  in `tests/statements/` under a plain name, and the anonymizer's `anonymize-*.json` mapping
  stays out of the repo.
