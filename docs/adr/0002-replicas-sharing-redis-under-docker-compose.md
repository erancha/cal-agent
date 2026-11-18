# 0002. Replicas under Docker Compose, sharing their tasks through Redis

- Status: Accepted
- Date: 2026-10-27

## Context

A caller's request for a month can pause for days while the person downloads a statement, and
the `continue` that resumes it may arrive anywhere. The agent should serve several people through
several callers, survive a restart, and show that it is safe to run more than one process. The
A2A SDK keeps tasks in memory by default, but defines a task store and an event stream that a
server spreads over replicas by implementing them. The demo runs on one machine, and amex-agent,
its first card agent, runs there as replicas under Docker Compose that share tasks through Redis.

## Decision

- A Docker Compose stack: two replicas of the agent, an nginx edge that alone publishes port 8030
  and spreads calls over them, and Redis with an append-only file written every second.
- The SDK's task store and event stream implemented on Redis: a versioned hash per task, written
  by one Lua script that refuses a stale save, and a Redis stream of each task's events.
- A lease of the repo's own in Redis naming the call that runs each task, renewed while it works;
  a sweep on every replica fails a working task left without a lease.
- The merchant memory in Redis too, so a merchant one replica decided costs no other a model call.
- Without `TASKS_REDIS_URL` everything stays in the process, for one replica: the unit tests and
  an agent run on the host.

## Consequences

- A paused task continues through any replica, a running one can be followed from any, and two
  continues sent at once run the task once.
- A replica stopped mid-task leaves a failed task within three lease periods, never a stuck one.
- The stack runs on one host; there is no cloud deployment to operate.
- Redeploying while a task works ends that task's stream, so redeploys wait for an idle agent.
