# 0001. An A2A server on the official Python SDK, serving one shared skill

- Status: Accepted
- Date: 2026-10-27

## Context

The home finance agent reviews a household's monthly spending across cards and asks a card agent
for one month's charges over the open A2A protocol. It owns and publishes the contract every card
agent serves: one skill, `monthly-transactions`, its request, its row format, its pauses and its
two credentials. The answer is a stream by design: rows in batches as they are ready, then
possibly a pause asking for a missing statement. amex-agent, the first card agent, runs on
Spring Boot with a transport of its own over the official Java library. cal-agent is the second
card agent, for Cal cards, and the official A2A SDK for Python (`a2a-sdk` 1.x) ships FastAPI
routes for JSON-RPC with SSE streaming, the Agent Card route, a request handler and interfaces
for its task store and event stream.

## Decision

- Python 3.14 with FastAPI on uvicorn, mounting the SDK's JSON-RPC and Agent Card routes as they
  ship; no transport code of the repo's own.
- The card work is one executor, the SDK's extension point; a subclass of the SDK's request
  handler refuses a request that must not start a task before the SDK creates one.
- Only `SendStreamingMessage` serves the skill; the blocking `SendMessage` is refused.
- The artifact schema and the taxonomy are the contract's: this repo implements them and never
  changes them on its own.

## Consequences

- The official A2A conformance suite runs against the same routes a caller calls.
- The SDK's behavior shows through: a task the executor raises in is stored failed, so refusals
  happen before the task starts, and the SDK ends the stream after a pause.
- Its task store and event stream interfaces are what the replicas share
  ([0002](0002-replicas-sharing-redis-under-docker-compose.md)).
- A caller written against the contract talks to cal-agent and amex-agent the same way.
