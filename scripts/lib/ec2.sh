#!/usr/bin/env bash
# The stack's EC2 target: the CloudFormation stack of scripts/template-ec2.yaml, and the instance's
# Docker daemon reached over SSH. The same file in every Docker Compose repo; the repo's own
# values come from scripts/lib/stack-params.sh (EC2_STACK, EC2_HOST_STACK, EC2_ORIGIN_PORT,
# EC2_INSTANCE_TYPE). Sourced by scripts/common.sh, never executed.
#
# Core responsibilities:
# - load_aws_config: the deploying user's credentials and region, from the gitignored
#   lib/aws-config.sh
# - resolve_ec2_stack / deploy_ec2_stack / resolve_ec2_host: the stacks the git branch selects
#   (this repo's and the host's), the deploy, and the instance and addresses
# - ec2_guest_slot: the host's security-group slot a guest stack opens its port in
# - prepare_ec2_host: the instance's Docker daemon answering, and its swap file in place
# - ssh_ec2 / use_ec2: a command on the instance, and Compose pointed at the instance's daemon
# - delete_ec2_stack: the stack's deletion, which leaves the instance's disk
#
# One instance serves several repos. The host repo (EC2_HOST_STACK blank) owns it; a guest repo
# names the host's stack in EC2_HOST_STACK, and its stack adds only a port, in one of the host's
# free security-group slots, and a CloudFront distribution. Each repo runs its own Compose
# project on the instance's one Docker daemon, on a port of its own.
#
# The instance accepts SSH as ec2-user with an EC2 Instance Connect key, valid for 60 seconds after
# each push and only for starting a connection, so every connection pushes the key first. One
# throwaway key pair stays on this machine, gitignored; no key is written to the instance.

EC2_TEMPLATE_FILE="$ROOT/scripts/template-ec2.yaml"
EC2_COMPOSE_FILE="$ROOT/docker-compose.ec2.yml"
EC2_HOST_USER='ec2-user'
# Swap on the instance, so a burst of memory beyond its RAM slows the stacks instead of killing a
# container: the instance is small, and several repos' stacks share it.
EC2_SWAP_SIZE='1G'
EC2_SSH_DIR="$ROOT/scripts/lib/.ssh"
EC2_SSH_OPTS=(-o StrictHostKeyChecking=accept-new -o ConnectTimeout=15 -o LogLevel=ERROR)
# The latest Amazon Linux 2023 image for ARM, which AWS publishes under this SSM parameter.
EC2_IMAGE_PARAMETER='/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64'

# The settings of aws-config.sh every AWS call needs.
AWS_SETTINGS=(AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_DEFAULT_REGION)

load_aws_config() {
  command -v aws >/dev/null || die "Required tool not found: aws"
  source_checked_file "$AWS_CONFIG_FILE" assert_secrets_untracked
  collect_missing_settings aws-config.sh "${AWS_SETTINGS[@]}"
  require_collected_settings
}

# Sets STACK_NAME from the git branch: main deploys EC2_STACK, any other branch EC2_STACK-fb; an
# exported STACK_NAME wins. Sets HOST_STACK_NAME to the stack that owns the instance: this one in
# the host repo, else EC2_HOST_STACK with the same suffix, so a feature branch's guest runs on the
# host repo's feature-branch instance. An exported HOST_STACK_NAME wins too, for a stack that is a
# guest of another stack of the same repo.
resolve_ec2_stack() {
  local suffix=''
  [[ "$(git -C "$ROOT" branch --show-current)" == main ]] || suffix='-fb'
  STACK_NAME="${STACK_NAME:-$EC2_STACK$suffix}"
  if [[ -z "$EC2_HOST_STACK" ]]; then
    HOST_STACK_NAME="${HOST_STACK_NAME:-$STACK_NAME}"
  else
    HOST_STACK_NAME="${HOST_STACK_NAME:-$EC2_HOST_STACK$suffix}"
  fi
}

ec2_is_host() { [[ "$HOST_STACK_NAME" == "$STACK_NAME" ]]; }

ec2_stack_exists() {  # [stack]
  aws cloudformation describe-stacks --stack-name "${1:-$STACK_NAME}" >/dev/null 2>&1
}

# A stack whose first creation failed is left in ROLLBACK_COMPLETE, holding no resources, and
# CloudFormation only allows deleting it; it is deleted so this deploy creates it again.
delete_failed_ec2_stack() {
  local status
  status="$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" \
    --query 'Stacks[0].StackStatus' --output text 2>/dev/null)" || return 0
  [[ "$status" == ROLLBACK_COMPLETE ]] || return 0
  echo "Stack $STACK_NAME failed its first creation and holds nothing; deleting it first..."
  aws cloudformation delete-stack --stack-name "$STACK_NAME"
  aws cloudformation wait stack-delete-complete --stack-name "$STACK_NAME"
}

# Prints the value of one output of a stack; fails when the stack lacks it.
ec2_stack_output() {  # stack key
  local value
  value="$(aws cloudformation describe-stacks --stack-name "$1" \
    --query "Stacks[0].Outputs[?OutputKey=='$2'].OutputValue" --output text)"
  [[ -n "$value" && "$value" != None ]] || die "Stack $1 has no output $2"
  printf '%s' "$value"
}

# The host stack's SSH rule admits one address, the last deployer's. A guest deploy from another
# address updates only that parameter of the host stack, its template and other values kept.
open_host_ssh_to() {  # cidr
  local current key
  local -a parameters=()
  current="$(aws cloudformation describe-stacks --stack-name "$HOST_STACK_NAME" \
    --query "Stacks[0].Parameters[?ParameterKey=='SshCidr'].ParameterValue" --output text)"
  [[ "$current" == "$1" ]] && return
  for key in $(aws cloudformation describe-stacks --stack-name "$HOST_STACK_NAME" \
                 --query 'Stacks[0].Parameters[].ParameterKey' --output text); do
    if [[ "$key" == SshCidr ]]; then
      parameters+=("ParameterKey=SshCidr,ParameterValue=$1")
    else
      parameters+=("ParameterKey=$key,UsePreviousValue=true")
    fi
  done
  echo "Opening SSH on host stack $HOST_STACK_NAME to this machine's address..."
  aws cloudformation update-stack --stack-name "$HOST_STACK_NAME" --use-previous-template \
    --parameters "${parameters[@]}" >/dev/null
  aws cloudformation wait stack-update-complete --stack-name "$HOST_STACK_NAME"
}

# Prints the host's slot this guest stack opens its port in: the one its stack already holds,
# else the first of the host's slots with no rule. Stops, before any change, when every slot is
# held, naming the stacks whose rules hold them.
ec2_guest_slot() {
  local held slot rules
  held="$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" \
    --query "Stacks[0].Parameters[?ParameterKey=='SlotGroupId'].ParameterValue" --output text \
    2>/dev/null)" || held=""
  if [[ -n "$held" && "$held" != None ]]; then printf '%s' "$held"; return; fi
  for slot in $(ec2_stack_output "$HOST_STACK_NAME" SlotGroupIds | tr ',' ' '); do
    rules="$(aws ec2 describe-security-groups --group-ids "$slot" \
      --query 'length(SecurityGroups[0].IpPermissions)' --output text)"
    if [[ "$rules" == 0 ]]; then printf '%s' "$slot"; return; fi
  done
  die "Every slot of host stack $HOST_STACK_NAME is held:" \
    "$(aws ec2 describe-security-groups \
         --group-ids $(ec2_stack_output "$HOST_STACK_NAME" SlotGroupIds | tr ',' ' ') \
         --query 'SecurityGroups[].IpPermissions[].PrefixListIds[].Description' --output text);" \
    "delete one of those stacks first"
}

# Prints the parameters only a new stack takes: the image, and a default subnet in an
# availability zone that offers the instance type. An existing stack keeps its own, since a
# change of either replaces the instance.
ec2_creation_parameters() {
  local image vpc zones subnet
  image="$(aws ssm get-parameter --name "$EC2_IMAGE_PARAMETER" \
    --query Parameter.Value --output text)"
  vpc="$(aws ec2 describe-vpcs --filters Name=is-default,Values=true \
    --query 'Vpcs[0].VpcId' --output text)"
  [[ "$vpc" != None ]] ||
    die "The region has no default VPC; create one first: aws ec2 create-default-vpc"
  zones="$(aws ec2 describe-instance-type-offerings --location-type availability-zone \
    --filters "Name=instance-type,Values=$EC2_INSTANCE_TYPE" \
    --query 'InstanceTypeOfferings[].Location' --output text | tr '\t' ',')"
  [[ -n "$zones" ]] || die "No availability zone of the region offers $EC2_INSTANCE_TYPE"
  subnet="$(aws ec2 describe-subnets \
    --filters "Name=vpc-id,Values=$vpc" Name=default-for-az,Values=true \
              "Name=availability-zone,Values=$zones" \
    --query 'sort_by(Subnets, &AvailabilityZone)[0].SubnetId' --output text)"
  [[ "$subnet" != None ]] || die "The default VPC has no default subnet in: $zones"
  printf 'ImageId=%s VpcId=%s SubnetId=%s' "$image" "$vpc" "$subnet"
}

# Creates or updates the stack. Port 22 of the host follows this machine's current public address
# on every run, the host's or a guest's.
deploy_ec2_stack() {
  local prefix_list my_address
  local -a parameters
  prefix_list="$(aws ec2 describe-managed-prefix-lists \
    --filters Name=prefix-list-name,Values=com.amazonaws.global.cloudfront.origin-facing \
    --query 'PrefixLists[0].PrefixListId' --output text)"
  [[ "$prefix_list" != None ]] || die "The region has no CloudFront origin-facing prefix list"
  my_address="$(curl -fsS --max-time 10 https://checkip.amazonaws.com)" ||
    die "Could not read this machine's public address from checkip.amazonaws.com"
  delete_failed_ec2_stack
  parameters=("OriginPort=$EC2_ORIGIN_PORT" "CloudFrontPrefixListId=$prefix_list")
  if ec2_is_host; then
    parameters+=("InstanceType=$EC2_INSTANCE_TYPE" "SshCidr=$my_address/32")
    if ! ec2_stack_exists; then
      local creation
      creation="$(ec2_creation_parameters)"
      # shellcheck disable=SC2206  # three Key=Value words, none with spaces
      parameters+=($creation)
    fi
  else
    ec2_stack_exists "$HOST_STACK_NAME" ||
      die "Host stack $HOST_STACK_NAME is not deployed; deploy it first from its repo:" \
          "./scripts/deploy.sh --ec2 (on the same kind of branch, main or not)"
    open_host_ssh_to "$my_address/32"
    parameters+=("HostStack=$HOST_STACK_NAME" "SlotGroupId=$(ec2_guest_slot)")
  fi
  echo "Deploying stack $STACK_NAME (a new CloudFront distribution takes several minutes)..."
  aws cloudformation deploy --stack-name "$STACK_NAME" --template-file "$EC2_TEMPLATE_FILE" \
    --no-fail-on-empty-changeset --parameter-overrides "${parameters[@]}"
}

# Sets EC2_INSTANCE_ID and EC2_HOST (the fixed public address) from the host stack, and EC2_URL
# (the CloudFront address) from this repo's.
resolve_ec2_host() {
  ec2_stack_exists || die "Stack $STACK_NAME is not deployed; run ./scripts/deploy.sh --ec2"
  EC2_INSTANCE_ID="$(ec2_stack_output "$HOST_STACK_NAME" InstanceId)"
  EC2_HOST="$(ec2_stack_output "$HOST_STACK_NAME" PublicAddress)"
  EC2_URL="$(ec2_stack_output "$STACK_NAME" CloudFrontUrl)"
}

# Prints the images this repo builds for the instance: by convention every image the Compose
# files tag :ec2. They are built here and loaded into the instance's daemon; the others, such as
# postgres, the daemon pulls itself.
ec2_built_images() {
  compose config --images | grep ':ec2$' | sort -u
}

push_ec2_ssh_key() {
  mkdir -p "$EC2_SSH_DIR" && chmod 700 "$EC2_SSH_DIR"
  [[ -f "$EC2_SSH_DIR/key" ]] || ssh-keygen -q -t ed25519 -N '' -f "$EC2_SSH_DIR/key"
  aws ec2-instance-connect send-ssh-public-key --instance-id "$EC2_INSTANCE_ID" \
    --instance-os-user "$EC2_HOST_USER" --ssh-public-key "file://$EC2_SSH_DIR/key.pub" \
    --query Success --output text >/dev/null
}

# Runs ssh to the instance with the given options and command; stdin and stdout pass through.
ssh_ec2() {
  push_ec2_ssh_key
  ssh -i "$EC2_SSH_DIR/key" -o "UserKnownHostsFile=$EC2_SSH_DIR/known_hosts" \
    "${EC2_SSH_OPTS[@]}" "$@"
}

# Waits up to about five minutes until the instance's Docker daemon answers ec2-user (a new
# instance installs Docker on its first boot), then makes sure the instance's swap file exists
# and is on, also across reboots. Every deploy runs it, the host stack's and a guest's, so an
# instance with no swap file gets one from whichever stack deploys to it first.
prepare_ec2_host() {
  local attempt ready=''
  for attempt in $(seq 30); do
    if ssh_ec2 "$EC2_HOST_USER@$EC2_HOST" docker info >/dev/null 2>&1; then ready=1; break; fi
    sleep 10
  done
  [[ -n "$ready" ]] ||
    die "The Docker daemon on $EC2_HOST did not answer; check the instance's first boot"
  ssh_ec2 "$EC2_HOST_USER@$EC2_HOST" sudo sh -s -- "$EC2_SWAP_SIZE" <<'SWAP'
swapon --show=NAME --noheadings | grep -qx /swapfile && exit 0
if [ ! -f /swapfile ]; then
  fallocate -l "$1" /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null
fi
swapon /swapfile
grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap defaults 0 0' >> /etc/fstab
SWAP
}

# Points docker and Compose of this shell at the instance's daemon: one SSH connection forwards
# the instance's Docker socket to a socket file on this machine, and closes when the script
# exits. Docker's own ssh:// endpoint opens a connection per command, which a pushed key would
# stop admitting after a minute. Both paths carry this script's process id, so runs at the same
# time (production's logs while a preview deploys) never close each other's connection.
open_ec2_docker() {
  local socket="$EC2_SSH_DIR/docker-$$.sock" control="$EC2_SSH_DIR/control-$$"
  rm -f "$socket"
  ssh_ec2 -f -N -T -M -S "$control" -o ExitOnForwardFailure=yes \
    -L "$socket:/var/run/docker.sock" "$EC2_HOST_USER@$EC2_HOST"
  # shellcheck disable=SC2064  # the paths are fixed now, not when the trap runs
  trap "ssh -S '$control' -O exit '$EC2_HOST_USER@$EC2_HOST' 2>/dev/null; rm -f '$socket'" EXIT
  export DOCKER_HOST="unix://$socket"
}

# Selects the EC2 target for the rest of the script: the stack's instance, its Compose override
# and its Docker daemon.
use_ec2() {
  load_aws_config
  resolve_ec2_stack
  resolve_ec2_host
  COMPOSE_FILES+=("$EC2_COMPOSE_FILE")
  open_ec2_docker
}

# Deletes the stack after the operator types its name, and waits until it is gone. A guest's
# deletion removes its distribution and its port; its containers and volumes stay on the instance
# unless docker-helper.sh --ec2 --stop [--volumes] removed them first. A host stack is deleted only
# once no guest stack imports its exports, which CloudFormation enforces; the instance's disk is
# not deleted on termination, so its volume id is read first and printed afterwards.
delete_ec2_stack() {
  local volume answer
  load_aws_config
  resolve_ec2_stack
  resolve_ec2_host
  if ec2_is_host; then
    volume="$(aws ec2 describe-instances --instance-ids "$EC2_INSTANCE_ID" \
      --query 'Reservations[0].Instances[0].BlockDeviceMappings[0].Ebs.VolumeId' --output text)"
    echo "This deletes host stack $STACK_NAME in $AWS_DEFAULT_REGION: the instance, its address,"
    echo "the security group and the CloudFront distribution at $EC2_URL. It fails while a guest"
    echo "stack runs on the instance; delete those first."
  else
    echo "This deletes guest stack $STACK_NAME in $AWS_DEFAULT_REGION: its port on the instance"
    echo "of $HOST_STACK_NAME and the CloudFront distribution at $EC2_URL."
  fi
  read -r -p "Type the stack's name to continue: " answer
  [[ "$answer" == "$STACK_NAME" ]] || die "Not deleted."
  aws cloudformation delete-stack --stack-name "$STACK_NAME"
  echo "Waiting for the stack to be deleted (the distribution takes several minutes)..."
  aws cloudformation wait stack-delete-complete --stack-name "$STACK_NAME"
  echo "Stack $STACK_NAME is deleted."
  if ec2_is_host; then
    echo "Its disk, volume $volume, holds the databases and stays in the account; delete it with:"
    echo "  aws ec2 delete-volume --volume-id $volume"
  fi
}
