#!/usr/bin/env bash
# Settings of the Compose stack that are neither secret nor private, committed so every checkout
# runs the same stack. Sourced by scripts/common.sh, never executed; the agent started on the host
# reads it too (src/calagent/platform/config.py), so every setting is one plain export line with a
# quoted value, which may name a key set above it as ${KEY}. Secrets are in secrets.sh and this
# deployment's own settings in params.sh, both gitignored.
#
# Compose hands the agent's replicas only the keys they read, listed in docker-compose.yml, and
# replaces the host forms of STATEMENTS_DIR and A2A_CALLERS_FILE with the paths inside the
# container. Every setting is read once, at startup, and a blank value counts as unset. A
# commented-out line shows an optional key at its default; uncomment it to set the key. Test-only
# keys are marked as such: leave them unset, the tests and tools/validate.sh set them.

# ── Ports ────────────────────────────────────────────────────────────────────────
# Read by docker-compose.yml only: the port the edge is published on, on this machine's loopback
# interface; the statements page and every A2A call arrive there, and a caller in Docker on this
# machine reaches it at host.docker.internal. Inside the Compose network the edge and the replicas
# always listen on 8030. It must be free on the host.
export EDGE_HOST_PORT="8030"
# The port an agent started on the host listens on (default 8030); compose sets 8030 in the
# containers.
# export SERVER_PORT="8030"

# ── EC2 ──────────────────────────────────────────────────────────────────────────
# Read by scripts/lib/ec2.sh only, for deploy.sh --ec2. The stack's name on main; any other
# branch deploys EC2_STACK-fb.
export EC2_STACK="cal-agent"
# This repo's stack is a guest on the instance of loan-simulator's stack, the host, which must be
# deployed first from its own repo.
export EC2_HOST_STACK="loan-simulator"
# The port CloudFront reaches this stack at on the instance; every stack on the instance has its
# own.
export EC2_ORIGIN_PORT="${EDGE_HOST_PORT}"

# ── Agent ────────────────────────────────────────────────────────────────────────
# The URL callers reach the agent at, published in the Agent Card; an A2A client calls this URL,
# not the one it fetched the card from. A caller running in Docker on this machine reaches the
# edge at host.docker.internal; a caller elsewhere needs this machine's hostname. Unset, it is
# http://localhost:<SERVER_PORT>. On the EC2 instance docker-compose.ec2.yml replaces it with the
# stack's CloudFront address.
export AGENT_URL="http://host.docker.internal:${EDGE_HOST_PORT}"
# Required: the root of the statement folders, one sub-folder per person named by their Google
# account id, holding the monthly statements downloaded from the card site. It starts empty; the
# statements page loads PDFs into the signed-in person's folder. deploy.sh creates it, a relative
# path under the repo, and compose mounts it into every replica at /statements. The agent refuses
# to start when it is not an existing directory. On the EC2 instance the statements live in the
# cal_statements volume instead.
export STATEMENTS_DIR="./statements"
# The folder holding statements.html. The image sets /app/static and compose does not pass this
# key.
# export STATIC_DIR="./static"

# ── Access ───────────────────────────────────────────────────────────────────────
# Require credentials: every A2A call carries the signed-in person's Google ID token as the bearer
# token and a registered caller's secret in X-Caller-Secret, and the statements API needs the
# person's token. The card, the health route, the statements page and /api/auth/config are always
# open. With it off there is one person, "anonymous", and no token or secret is read.
# export A2A_AUTH_REQUIRED="true"
# The file registering the A2A callers, written by ./scripts/tools/register-caller.sh: for each
# caller its name, the secret it presents and the Google OAuth client id whose tokens it
# forwards. While access is required, startup refuses an empty file, a caller with a blank field
# and two callers sharing a secret or a name. Compose copies its content into every replica at
# /allowed-callers.yaml.
# export A2A_CALLERS_FILE="./allowed-callers.yaml"
# Who issues the tokens and where its public keys are published; both are read only when a token
# is verified.
# export AUTH_ISSUER="https://accounts.google.com"
# export AUTH_JWKS_URL="https://www.googleapis.com/oauth2/v3/certs"
# Test only: a PEM public key that replaces AUTH_JWKS_URL, so tests can sign their own tokens.
# export AUTH_PUBLIC_KEY_FILE=""

# ── Categorization ───────────────────────────────────────────────────────────────
# The model's score (0 to 1) from which a row's confidence is reported as "high" and as
# "medium"; below the medium one it is "low". Startup refuses a medium threshold above the high
# one or either outside 0 to 1.
# export CATEGORIZER_HIGH_CONFIDENCE="0.85"
# export CATEGORIZER_MEDIUM_CONFIDENCE="0.6"
# How many not-yet-seen merchants go to the model in one call, at least 1.
# export CATEGORIZER_BATCH_SIZE="40"

# ── Tasks ────────────────────────────────────────────────────────────────────────
# Redis shared by the replicas: the A2A tasks and their events, so a task paused by one replica
# can be continued or followed on any, even after a restart; which replica runs each task; and
# the merchant categories remembered per person. When unset, all of it stays in the process's
# memory, for a single replica. Compose sets the in-network address, redis://redis:6379/0.
# export TASKS_REDIS_URL="redis://localhost:6379/0"
# How long Redis keeps a task after its last change, as an ISO 8601 duration or a number of
# seconds.
# export TASKS_TTL="P30D"
# Seconds a task's lease, which only the call running the task holds, lasts unless renewed (at
# least 1); the running call renews it every third of this. With Redis, each replica also checks
# this often for working tasks nobody holds, left by a replica that stopped, and fails them so
# the caller can start again.
# export TASK_LEASE_SECONDS="60"
# Test only: "tck" swaps in the scenario executor the conformance suite needs and turns access
# off; tools/validate.sh --tck sets it. The default is "card".
# export A2A_EXECUTOR="card"
# Test only: milliseconds every call to the classifier waits first, so the multi-replica tests
# can act while a task is still working.
# export CAL_TEST_SLOW_MS="0"

# ── Logging ──────────────────────────────────────────────────────────────────────
# The level for the agent and for the A2A SDK.
# export LOG_LEVEL="INFO"
# export A2A_LOG_LEVEL="WARNING"
