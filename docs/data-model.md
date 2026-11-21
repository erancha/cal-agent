# Data model

This document details the storage that [Architecture](architecture.md#storage) summarizes: every
Redis key the replicas share, the statements root and the callers registry.

## Redis

Redis is shared by the replicas: a hash per task, `cal:task:<id>`, with the set of task ids
`cal:tasks`; a stream of each task's events, `cal:events:<id>`; a lease per running task,
`cal:lease:<id>`; and the merchant memory, a hash per person, `cal:merchants:<sub>`. A task
expires `TASKS_TTL` after its last save, the memory never. Redis writes an append-only file every
second to the `cal_redis` volume. How the task store, the event stream and the lease use these
keys is in [Scaling](architecture/scaling.md#scaling-safety), the merchant memory in
[The merchant memory](architecture/categorizer.md#the-merchant-memory).

## The statements root

`STATEMENTS_DIR` (`./statements` in `stack-params.sh`), mounted into every replica, or the
`cal_statements` volume on the EC2 instance: a folder per Google account id, each PDF named for
its billing month ([One folder per person](architecture/statements.md#one-folder-per-person)).

## The callers registry

`allowed-callers.yaml`, the gitignored callers file `tools/register-caller.sh` writes, which
Compose copies into each replica and the replica reads at startup: each caller's name, secret and
Google client id.
