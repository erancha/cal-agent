#!/usr/bin/env bash
#
# Deploy cal-agent: build the images and start Redis, two replicas of the agent and the nginx
# edge in Docker Compose, then return once the edge answers.
#
#   ./scripts/deploy.sh          on this machine's Docker
#   ./scripts/deploy.sh --ec2    on the EC2 instance of loan-simulator's stack, as a guest behind
#                                a CloudFront distribution of its own
#   -h, --help                   show this help
#
# The agent refuses to start when LLM_MODEL is blank, when LLM_API_KEY is blank for a model other
# than keyword, or, while access is required, when AUTH_CLIENT_ID is blank or no A2A caller is
# registered, so the script checks them first and names every blank setting with its settings
# file. Every run starts with ./scripts/init-env.sh, which creates a missing settings file and
# keeps the existing ones, so a first run creates them all and then stops on the settings left to
# fill in. Register each caller with ./scripts/tools/register-caller.sh; the script ends with the
# values a caller's operator records, the secret aside. Stop or inspect the stack with
# ./scripts/docker-helper.sh (--stop / --logs / --ps), which takes --ec2 too.
#
# On this machine the edge is published on the loopback interface at EDGE_HOST_PORT (8030 as
# shipped), where a caller in Docker reaches it at host.docker.internal. The statements page is
# http://localhost:8030/statements.html, and the statements live in the STATEMENTS_DIR folder.
#
# --ec2 also needs the access key pair and region in scripts/lib/aws-config.sh, and deploys to
# the account its credentials belong to. Deploy loan-simulator's stack first, from its repo: it
# owns the instance. This script creates or updates this repo's CloudFormation stack of
# scripts/template-ec2.yaml (the git branch selects it: cal-agent on main, cal-agent-fb on any
# other branch), which opens EDGE_HOST_PORT on the instance to CloudFront and adds a distribution
# whose https address is the way in. It then builds the images here for ARM, loads them into the
# instance's Docker daemon over SSH, and runs Compose against that daemon. The settings files and
# the callers registry stay on this machine; each container's own settings, secrets included,
# reach the instance as part of the container's configuration, which Docker keeps on the
# instance's encrypted disk. On the instance the card advertises the CloudFront address, and the
# statements live in the cal_statements volume, loaded through the statements page at that
# address. Register the printed address with Google once (docs/sign-in.md).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

TARGET=local
case "${1:-}" in
  -h|--help) print_help; exit 0 ;;
  --ec2)     TARGET=ec2 ;;
  "")        ;;
  *)         print_help >&2; exit 2 ;;
esac

"$SCRIPT_DIR/init-env.sh"
load_settings
collect_missing_settings stack-params.sh EDGE_HOST_PORT STATEMENTS_DIR
collect_missing_settings params.sh LLM_MODEL
# The keyword table needs no key, and with access off no token is verified.
[[ "${LLM_MODEL:-}" == keyword ]] || collect_missing_settings secrets.sh LLM_API_KEY
[[ "${A2A_AUTH_REQUIRED:-true}" == false ]] || collect_missing_settings params.sh AUTH_CLIENT_ID
require_collected_settings
require_callers_file
require_docker

print_card_url() {
  echo "cal-agent -> $(page_url)   card: $(page_url)/.well-known/agent-card.json"
  print_handover "each A2A caller's operator" \
    "the one register-caller.sh printed when it registered that caller"
}

deploy_local() {
  local base="http://localhost:$EDGE_HOST_PORT"
  ensure_statements_dir
  echo "Building and starting Redis, the agent's replicas and the edge..."
  compose up -d --build
  wait_for_http "$base/health" \
    || { echo "the agent did not answer on $base; see ./scripts/docker-helper.sh --logs" >&2
         exit 1; }
  print_card_url
  echo "  stop it or tail logs:  ./scripts/docker-helper.sh --stop | --logs"
}

deploy_ec2() {
  load_aws_config
  resolve_ec2_stack
  deploy_ec2_stack
  resolve_ec2_host
  COMPOSE_FILES+=("$EC2_COMPOSE_FILE")

  echo "Building the images for linux/arm64 on this machine..."
  compose build
  prepare_ec2_host
  echo "Loading the images into the instance's Docker daemon..."
  # shellcheck disable=SC2046  # one image name per word, none with spaces
  docker save $(ec2_built_images) | gzip | ssh_ec2 "$EC2_HOST_USER@$EC2_HOST" 'gunzip | docker load'

  open_ec2_docker
  echo "Starting Redis, the agent's replicas and the edge on the instance..."
  compose up -d --no-build --remove-orphans
  # A deploy leaves the previous build's layers behind; the instance's disk is small.
  docker image prune -f >/dev/null
  wait_for_http "$EC2_URL/health" \
    || { echo "the agent did not answer on $EC2_URL/health;" \
              "see ./scripts/docker-helper.sh --ec2 --logs" >&2
         exit 1; }
  print_card_url
  echo "  Register it with Google once: $EC2_URL as an authorized JavaScript origin of the"
  echo "  agent's OAuth client (docs/sign-in.md)."
  echo "  stop it or tail logs:  ./scripts/docker-helper.sh --ec2 --stop | --logs"
}

"deploy_$TARGET"
