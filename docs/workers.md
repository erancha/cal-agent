# Workers' responsibilities and flows

This document details the work no request waits on, behind the parts that
[Architecture](architecture.md#the-parts) summarizes: the lease sweep that every `cal-agent`
replica runs beside the requests it serves. The guarantees the sweep carries are in
[Scaling](architecture/scaling.md#scaling-safety), the routes in [API endpoints](api.md).

## `LeaseSweep`

`LeaseSweep` in `platform/a2a/sweep.py` starts with the app, as a background task beside the
requests, and only when the replicas share Redis (`TASKS_REDIS_URL`); an agent that keeps its
tasks in its own memory runs none.

Every replica runs a sweep at startup and then every lease period. It reads the working tasks of
every caller, and a task found without a lease on two passes in a row, at the same version, was
left by a replica that stopped. The sweep saves it `TASK_STATE_FAILED` with the text
`stopped while reading 2026-10; start the review again`, publishes that status to the task's event
stream, so a subscriber on any replica sees the end, then deletes the stream. Two passes, because
a replica releases the lease a moment before the SDK saves the task's final state, and one pass
could fall in between. Of two replicas failing one task, the task store's version check lets one
win ([The task store and event stream](architecture/scaling.md#the-task-store-and-event-stream)).

A pass that cannot reach Redis is logged and retried at the next interval, so a Redis restart does
not end the sweep. Any other error ends it, and the replica's `/health` then answers 503 `DOWN`,
reporting the replica unhealthy rather than letting it go on without recovery.
