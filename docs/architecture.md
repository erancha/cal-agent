# Architecture

How cal-agent is built, and why. Each section below ends in a page that holds its details. What
goes on the wire is in [a2a-contract.md](a2a-contract.md); how each part is tested is in
[testing.md](testing.md).

## Request flow

The architecture diagram in [the README](../README.md#architecture) walks a request through its
boxes. [architecture/request-flow.md](architecture/request-flow.md) is what runs inside a
replica: how the two credentials are checked, how a request is admitted before its task starts,
and how the official A2A SDK's routes and request handler carry the stream.

## Statements

One folder per person under the statements root, where a static page lets a person load and
delete their own files. On every lookup the agent reads the folder's PDFs and maps each to the
billing month it declares, so a file loaded while a task waits is found on `continue`. The parser
reads the Hebrew right-to-left table by word positions and checks the rows against the printed
total. [architecture/statements.md](architecture/statements.md)

## Categorizer

A language model categorizes each merchant once per person, in batches, guided by the sector label
the statement prints, and its score becomes `high`, `medium` or `low` confidence. Decisions are
remembered in Redis, so a repeated month costs no model call on any replica. Amounts and dates
never pass through the model. [architecture/categorizer.md](architecture/categorizer.md)

## Scaling

The Docker stack runs several replicas of the agent behind an nginx edge. They share through Redis
the A2A tasks and their events, on the task store and event stream interfaces the A2A SDK defines
for running over replicas, and two parts of the agent's own: a lease naming the call that runs each
task, and the merchant memory. Two concerns follow, each a GitHub label beside `scalability`:
**scaling safety**, that it is safe to run more than one replica without errors; and **scaling
out**, that adding replicas serves more callers without degrading any caller's experience.
[architecture/scaling.md](architecture/scaling.md)

## Configuration

Every runtime setting is an environment variable; secrets, the model and the statements folder have
no default, and a wrong required setting stops startup naming it.
[architecture/configuration.md](architecture/configuration.md)

## Codebase structure

One package in layers: the domain values at the center, the ports the card work depends on, the
month pipeline, the adapters to the outside world, and the platform that fits it all into the A2A
SDK and FastAPI. [architecture/codebase-structure.md](architecture/codebase-structure.md)
