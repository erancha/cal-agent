# 0008. The stack can host the EC2 instance or join another repo's

- Status: Accepted
- Date: 2026-11-18

## Context

[ADR 0007](0007-guest-on-loan-simulators-ec2-instance.md) made the stack a guest of loan-simulator's
stack, and the committed `stack-params.sh` named that host. A person who cloned this repo without
loan-simulator had no such stack, so `deploy.sh --ec2` stopped on a missing host. Which repos share
an instance is a choice of each deployment, not a property of a repo.

## Decision

`EC2_HOST_STACK` moves to the gitignored `params.sh`, blank in `params.example.sh`. Blank, the stack
is a host with an instance of its own; set to another Docker Compose repo's host stack, the stack is
a guest on that stack's instance, as ADR 0007 describes. `stack-params.sh` commits
`EC2_INSTANCE_TYPE`, which only a host uses. The rest of ADR 0007 holds.

## Consequences

- The repo deploys alone, and any repo of the group can be the host of the others; a person who
  can afford several instances makes several repos hosts.
- The host goes first, and CloudFormation refuses to delete it while a guest imports its exports.
- Moving the host to another repo starts a new instance with an empty disk, so the stack's
  volumes start empty.
