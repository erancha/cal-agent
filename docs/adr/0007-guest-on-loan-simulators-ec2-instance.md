# 0007. A guest on loan-simulator's EC2 instance, behind a CloudFront distribution of its own

- Status: Accepted
- Date: 2026-11-16

## Context

The stack ran only on a workstation under Docker Compose
([ADR 0002](0002-replicas-sharing-redis-under-docker-compose.md)), and Google sign-in accepts only
`localhost` or a public hostname, so nobody away from that machine could load a statement. The
Docker Compose repos of the demo share one deployment scheme: loan-simulator's stack owns one ARM
instance with Docker, behind CloudFront, and the other repos join it as guests. The stack
bind-mounted the edge's configuration, the callers registry and the statements folder from the
workstation, and none of them exists on the instance.

## Decision

`deploy.sh --ec2` runs the same Compose stack on loan-simulator's instance, as the guest stack
`cal-agent` of the shared template, `scripts/template-ec2.yaml`.

- The guest stack opens the edge's port, 8030, to CloudFront's servers in the host's security
  group and adds its own CloudFront distribution, whose https address is the way in. TLS ends at
  CloudFront; the hop to the edge is plain HTTP.
- The images are built on the deployer's machine for ARM and loaded into the instance's Docker
  daemon over SSH; Compose runs there against that daemon. No registry or secret store.
- No file is bind-mounted on the instance, and only the statements folder on the workstation: the
  edge's configuration is part of its image, and Compose copies the callers registry into each
  replica when it creates it, labelled with the registry's digest so a change recreates them.
- On the instance the statements live in a named volume, loaded through the statements page at
  the CloudFront address, and the card advertises that address.

## Consequences

- No load balancer, container service or file store to pay for or operate; the stack shares the
  instance's memory with three others, and the host stack's instance is a single point of failure.
- A caller on the instance, such as the home finance agent, calls the advertised CloudFront
  address, so its streams cross CloudFront, whose origin read timeout is 30 seconds; the SDK's
  keep-alive comment every 15 seconds keeps a stream inside it.
- The statements stay on the instance's disk, which has no snapshots; a replaced instance starts
  with none, and each person loads their statements again.
