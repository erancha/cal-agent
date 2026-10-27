# Scaling

The Docker stack runs the agent as several replicas behind an nginx edge, all on one Redis and one
statements folder, so a caller sees one agent whichever replica serves it. This page states what
the replicas guarantee and the mechanisms that carry each guarantee.

## Scaling safety

Several replicas of the agent behave exactly as one would: a replica may start or stop, calls may
land on any replica in any order, and the caller sees the same result as from a single process.
In particular:

- **A stopped replica leaves a failed task, never a stuck one.** A replica stopped while a task
  works leaves the caller a `TASK_STATE_FAILED` task within three lease periods, with a text asking
  to start again, and the month can be fetched again at once.
- **A continue runs once.** Two continues sent at once for one paused task, to one replica or two,
  run it once; the other is refused as already running.
- **A subscribe reaches the running task.** `SubscribeToTask` sent to any replica streams the
  events of the replica running the task, from the version the caller was served onwards.
- **A paused task waits on any replica.** Whichever replica receives the `continue` loads the
  paused task, with the month and person recorded when it paused.

What a request needs therefore crosses processes: the person is a token verified on every request,
every replica mounts the same statements folder, and every task, its events and its lease are kept
in Redis. Without Redis, as in `start.sh --host` and the unit tests, all of it stays in the
process's memory, for a single replica. What is still open under this term is tracked in this
repo's GitHub issues: the `scalability` label with the `scaling-safety` label.

### The task store and event stream

The A2A SDK defines how a server spreads over replicas, and the agent implements those interfaces
on Redis rather than a scheme beside them. The task store is versioned: each task is a hash,
`cal:task:<id>`, holding the task, the caller that owns it and a version that every save raises by
one, and a save names the version it read. One Lua script compares and writes, so a save from a
stale version, or by another caller, is refused and the SDK refuses the stale write in turn. Every
save resets the task's time to live, `TASKS_TTL` (30 days by default).

Each task's events go to a Redis stream, `cal:events:<id>`, each entry tagged with the version it
produced. A replica serving `SubscribeToTask` sends the stored task, then reads the stream from its
start, skipping the versions the stored task already holds, and follows it until the task
completes, fails or pauses. A stream rather than a publish-and-subscribe channel, because a
subscriber that arrives late must replay what it missed.

Redis writes all of it to an append-only file every second, so a paused task survives a restart of
Redis.

### The lease

The SDK has no notion of which replica runs a task, so the agent adds one. A lease,
`cal:lease:<taskId>`, holds the owner of one request: the replica's identity and a call id. It is
taken only when free, before the task turns `TASK_STATE_WORKING`, with a time to live of
`TASK_LEASE_SECONDS` (60 by default); the executor renews it every third of that while it works and
releases it when the task pauses, completes or fails. Of two continues reaching two replicas at
once, the second cannot take the lease and is refused before its task resumes, with the store's
version check as the net under it. A request whose caller disconnects never releases a lease early:
the run it started may still be working, so the lease expires with its time to live.

### The sweep

Every replica runs a sweep at startup and then every lease period. It reads the working tasks of
every caller, and a task found without a lease on two passes in a row, at the same version, was
left by a replica that stopped. The sweep saves it `TASK_STATE_FAILED` with the text
`stopped while reading 2026-10; start the review again`, publishes that status to the task's event
stream, so a subscriber on any replica sees the end, then deletes the stream. Two passes, because
a replica releases the lease a moment before the SDK saves the task's final state, and one pass
could fall in between. Of two replicas failing one task, the version check lets one win.

A pass that cannot reach Redis is logged and retried at the next interval, so a Redis restart does
not end the sweep. Any other error ends it, and the replica's `/health` then answers 503 `DOWN`,
reporting the replica unhealthy rather than letting it go on without recovery.

## Scaling out

Scaling out, as this page and the `scaling-out` label use the term, is scalability in the classic
sense: the agent serves more callers by adding replicas, and a caller's experience, the time a
month takes to fetch and categorize, stays what it is from a single replica. Beyond the shared
statements folder and task store, one thing carries this: a merchant costs one model call per
person, whichever replica meets it first. The merchant memory ([categorizer.md](categorizer.md))
is a Redis hash per person, `cal:merchants:<sub>`, kept without expiry, so a month fetched through
any replica, or after any restart, is categorized as fast as through the one that saw its merchants
first. What is still open under this term is tracked in this repo's GitHub issues: the
`scalability` label with the `scaling-out` label.

## The edge service

An nginx service, `edge`, is the only one that publishes port 8030, and it spreads calls over the
replicas. It looks up the replicas' addresses again every 5 seconds, so a replica added by scaling
or recreated by a redeploy starts receiving calls without an edge restart. It passes each response
on as it arrives, so the stream's events reach the caller one by one, and waits up to 300 seconds
for the next one, since a stream is silent while the model categorizes a month. It admits uploads
up to 6 MB, so a file just over the agent's 5 MB limit reaches the agent's own refusal, which names
the limit. Its access log names the replica that served each call
(`docker-helper.sh --logs edge`). `start.sh --host` has no edge: the one process serves the port
itself.
