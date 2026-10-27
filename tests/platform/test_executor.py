import asyncio
from pathlib import Path

import pytest
from a2a.helpers import get_data_parts
from a2a.server.context import ServerCallContext
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    CancelTaskRequest,
    GetTaskRequest,
    ListTasksRequest,
    StreamResponse,
    Task,
    TaskState,
)
from a2a.utils.errors import (
    A2AError,
    InvalidParamsError,
    TaskNotCancelableError,
    TaskNotFoundError,
    UnsupportedOperationError,
)

from calagent.adapters.tasks.memory_lease import InMemoryLease
from calagent.domain.errors import StatementMissing
from calagent.domain.rows import TransactionRow
from calagent.domain.taxonomy import TAXONOMY
from calagent.platform.a2a.callers import CALLER_STATE_KEY
from calagent.platform.a2a.card import build_agent_card
from calagent.platform.a2a.context import AUTH_FAILURE_KEY, PERSON_KEY, CallerUser
from calagent.platform.a2a.executor import CardAgentExecutor
from calagent.platform.a2a.handler import CardRequestHandler
from calagent.ports.tokens import VerifiedPerson
from tests.auth_keys import OTHER_CALLER_CLIENT_ID, PAGE_CLIENT_ID, sign
from tests.platform.support import (
    CALLER,
    OTHER_SECRET,
    PERSON,
    FixedMonth,
    a2a_client,
    artifact_updates,
    ask,
    http_client,
    ids,
    made_up_row,
    make_app,
    make_settings,
    pause_parts,
    place_fixture,
    request,
    rows_of,
    statement_path,
    states,
    validator,
)

COVERED = {"month": "2026-10"}
UNCOVERED = {"month": "2026-09"}
CONTINUE = {"action": "continue"}
ROW_FIELDS = {
    "id",
    "transactionDate",
    "chargeDate",
    "merchant",
    "rawMerchant",
    "amount",
    "originalAmount",
    "originalCurrency",
    "standingOrder",
    "abroad",
    "installment",
    "category",
    "confidence",
}
STATEMENT_MISSING = {
    "reason": "statement-missing",
    "month": "2026-09",
    "page": "/statements.html",
    "user": "1000",
}


async def test_a_covered_month_streams_19_rows_in_one_artifact_and_completes(
    tmp_path: Path,
) -> None:
    async with await a2a_client(make_app(tmp_path), sign()) as client:
        events = await ask(client, COVERED)

    assert states(events) == ["TASK_STATE_SUBMITTED", "TASK_STATE_WORKING", "TASK_STATE_COMPLETED"]
    [update] = artifact_updates(events)
    assert update.artifact.artifact_id == f"transactions-{ids(events)['task_id']}"
    assert update.artifact.name == "transactions"
    assert (update.append, update.last_chunk) == (False, True)
    rows = rows_of(events)
    assert len(rows) == 19
    assert all(set(row) == ROW_FIELDS for row in rows)
    assert all(row["category"] in TAXONOMY for row in rows)
    unknown = [row for row in rows if "גפניקה" in row["rawMerchant"]]
    assert unknown
    assert all((r["category"], r["confidence"]) == ("uncategorized", "low") for r in unknown)


async def test_the_working_status_names_the_month(tmp_path: Path) -> None:
    async with await a2a_client(make_app(tmp_path), sign()) as client:
        events = await ask(client, COVERED)

    working = next(e.status_update.status for e in events if e.HasField("status_update"))
    assert working.state == TaskState.TASK_STATE_WORKING
    assert working.message.parts[0].text == "Parsing statement for 2026-10"


async def test_an_empty_statement_sends_one_empty_batch(tmp_path: Path) -> None:
    async with await a2a_client(make_app(tmp_path, monthly=FixedMonth([])), sign()) as client:
        events = await ask(client, COVERED)

    [update] = artifact_updates(events)
    assert (update.append, update.last_chunk) == (False, True)
    assert rows_of(events) == []
    assert states(events)[-1] == "TASK_STATE_COMPLETED"


async def test_26_rows_stream_as_two_chunks_of_one_artifact(tmp_path: Path) -> None:
    month = FixedMonth([made_up_row(n) for n in range(1, 27)])
    async with await a2a_client(make_app(tmp_path, monthly=month), sign()) as client:
        events = await ask(client, COVERED)

    first, second = artifact_updates(events)
    assert first.artifact.artifact_id == second.artifact.artifact_id
    assert (first.append, first.last_chunk) == (False, False)
    assert (second.append, second.last_chunk) == (True, True)
    assert len(rows_of(events)) == 26


async def test_an_uncovered_month_pauses_with_the_statement_missing_parts(tmp_path: Path) -> None:
    async with await a2a_client(make_app(tmp_path), sign()) as client:
        events = await ask(client, UNCOVERED)

    assert states(events)[-1] == "TASK_STATE_INPUT_REQUIRED"
    assert pause_parts(events) == ("No statement covers 2026-09.", STATEMENT_MISSING)


async def test_continue_after_the_file_lands_completes_the_same_task(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    statement_path(tmp_path).unlink()
    async with await a2a_client(app, sign()) as client:
        paused = await ask(client, COVERED)
        assert states(paused)[-1] == "TASK_STATE_INPUT_REQUIRED"
        place_fixture(tmp_path)
        events = await ask(client, CONTINUE, **ids(paused))

    assert states(events) == ["TASK_STATE_WORKING", "TASK_STATE_COMPLETED"]
    assert {u.task_id for u in artifact_updates(events)} == {ids(paused)["task_id"]}
    assert len(rows_of(events)) == 19


async def test_continue_without_a_file_pauses_again(tmp_path: Path) -> None:
    async with await a2a_client(make_app(tmp_path), sign()) as client:
        paused = await ask(client, UNCOVERED)
        events = await ask(client, CONTINUE, **ids(paused))

    assert states(events) == ["TASK_STATE_WORKING", "TASK_STATE_INPUT_REQUIRED"]
    assert pause_parts(events) == ("No statement covers 2026-09.", STATEMENT_MISSING)


async def test_a_bad_month_is_invalid_params_and_leaves_no_task(tmp_path: Path) -> None:
    async with await a2a_client(make_app(tmp_path), sign()) as client:
        with pytest.raises(InvalidParamsError, match="2026-9"):
            await ask(client, {"month": "2026-9"})
        tasks = await client.list_tasks(ListTasksRequest())

    assert list(tasks.tasks) == []


async def test_continue_on_a_completed_task_is_invalid_params(tmp_path: Path) -> None:
    async with await a2a_client(make_app(tmp_path), sign()) as client:
        done = await ask(client, COVERED)
        with pytest.raises(InvalidParamsError, match="TASK_STATE_COMPLETED"):
            await ask(client, CONTINUE, **ids(done))


async def test_a_month_on_a_paused_task_is_invalid_params(tmp_path: Path) -> None:
    async with await a2a_client(make_app(tmp_path), sign()) as client:
        paused = await ask(client, UNCOVERED)
        with pytest.raises(InvalidParamsError, match="continue"):
            await ask(client, COVERED, **ids(paused))
        task = await client.get_task(GetTaskRequest(id=ids(paused)["task_id"]))

    assert task.status.state == TaskState.TASK_STATE_INPUT_REQUIRED


async def test_continue_while_another_replica_runs_the_task_is_refused(tmp_path: Path) -> None:
    lease = InMemoryLease(60)
    async with await a2a_client(make_app(tmp_path, lease=lease), sign()) as client:
        paused = await ask(client, UNCOVERED)
        task_id = ids(paused)["task_id"]
        assert await lease.acquire(task_id, "other-replica")
        with pytest.raises(UnsupportedOperationError, match="already running"):
            await ask(client, CONTINUE, **ids(paused))
        task = await client.get_task(GetTaskRequest(id=task_id))

    assert task.status.state == TaskState.TASK_STATE_INPUT_REQUIRED
    assert await lease.owner_of(task_id) == "other-replica"


async def test_no_token_pauses_in_auth_required(tmp_path: Path) -> None:
    async with await a2a_client(make_app(tmp_path), None) as client:
        events = await ask(client, COVERED)

    assert states(events) == ["TASK_STATE_SUBMITTED", "TASK_STATE_AUTH_REQUIRED"]
    text, data = pause_parts(events)
    assert "could not verify who you are" in text
    assert data == {"reason": "sign-in-required", "month": "2026-10", "user": ""}


async def test_a_page_client_token_is_refused_on_a2a(tmp_path: Path) -> None:
    async with await a2a_client(make_app(tmp_path), sign(aud=PAGE_CLIENT_ID)) as client:
        events = await ask(client, COVERED)

    assert states(events)[-1] == "TASK_STATE_AUTH_REQUIRED"
    assert "issued for another application" in pause_parts(events)[0]


async def test_continue_after_signing_in_completes_for_the_signed_in_person(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)
    async with await a2a_client(app, None) as anonymous:
        paused = await ask(anonymous, COVERED)
    async with await a2a_client(app, sign()) as client:
        events = await ask(client, CONTINUE, **ids(paused))

    assert states(events)[-1] == "TASK_STATE_COMPLETED"
    assert len(rows_of(events)) == 19


async def test_continue_from_another_account_is_auth_required(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    async with await a2a_client(app, sign()) as client:
        paused = await ask(client, UNCOVERED)
    async with await a2a_client(app, sign(sub="2000")) as other:
        events = await ask(other, CONTINUE, **ids(paused))

    assert states(events) == ["TASK_STATE_AUTH_REQUIRED"]
    text, data = pause_parts(events)
    assert "different Google account" in text
    assert data == {"reason": "sign-in-required", "month": "2026-09", "user": "1000"}


async def test_a_token_for_another_callers_client_is_auth_required(tmp_path: Path) -> None:
    async with await a2a_client(make_app(tmp_path), sign(), secret=OTHER_SECRET) as client:
        events = await ask(client, COVERED)

    assert states(events) == ["TASK_STATE_SUBMITTED", "TASK_STATE_AUTH_REQUIRED"]
    assert "issued for another application" in pause_parts(events)[0]


async def test_another_caller_cannot_continue_a_callers_task(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    async with await a2a_client(app, sign()) as client:
        paused = await ask(client, UNCOVERED)
        other_token = sign(aud=OTHER_CALLER_CLIENT_ID)
        async with await a2a_client(app, other_token, secret=OTHER_SECRET) as other:
            with pytest.raises(TaskNotFoundError):
                await ask(other, CONTINUE, **ids(paused))
        task = await client.get_task(GetTaskRequest(id=ids(paused)["task_id"]))

    assert task.status.state == TaskState.TASK_STATE_INPUT_REQUIRED


async def test_wrong_secret_is_401_before_jsonrpc(tmp_path: Path) -> None:
    async with http_client(make_app(tmp_path), sign(), secret="wrong") as http:
        response = await http.post("/", json={"jsonrpc": "2.0", "id": 1, "method": "GetTask"})

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "X-Caller-Secret"
    assert response.content == b""


async def test_the_card_and_health_need_no_secret(tmp_path: Path) -> None:
    async with http_client(make_app(tmp_path), None, secret=None) as http:
        health = await http.get("/health")
        card = await http.get("/.well-known/agent-card.json")

    assert (health.status_code, health.json()) == (200, {"status": "UP"})
    assert card.status_code == 200


async def test_a_parse_failure_fails_the_task_with_the_cause(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    statement_path(tmp_path).write_bytes(b"%PDF-1.4 nothing")
    async with await a2a_client(app, sign()) as client:
        events = []
        with pytest.raises(A2AError) as failure:
            async for event in client.send_message(request(COVERED)):
                events.append(event)
        task = await client.get_task(GetTaskRequest(id=ids(events)["task_id"]))

    assert str(failure.value).startswith("could not read 2026-10.pdf: it is not a readable PDF")
    assert task.status.state == TaskState.TASK_STATE_FAILED


async def test_cancel_a_paused_task_then_a_terminal_one(tmp_path: Path) -> None:
    async with await a2a_client(make_app(tmp_path), sign()) as client:
        paused = await ask(client, UNCOVERED)
        task_id = ids(paused)["task_id"]
        canceled = await client.cancel_task(CancelTaskRequest(id=task_id))
        with pytest.raises(TaskNotCancelableError):
            await client.cancel_task(CancelTaskRequest(id=task_id))

    assert canceled.status.state == TaskState.TASK_STATE_CANCELED


class GatedMonth(FixedMonth):
    """Holds every fetch until the test opens the gate."""

    def __init__(self) -> None:
        super().__init__([made_up_row(1)])
        self.gate = asyncio.Event()

    async def fetch(self, person: str, month: str) -> list[TransactionRow]:
        await self.gate.wait()
        return await super().fetch(person, month)


async def test_lease_is_held_and_renewed_while_working_and_released_after(
    tmp_path: Path,
) -> None:
    lease = InMemoryLease(1)
    month = GatedMonth()
    app = make_app(tmp_path, monthly=month, lease=lease, task_lease_seconds=1)
    async with await a2a_client(app, sign()) as client:
        running = asyncio.create_task(ask(client, COVERED))
        working = []
        while not working:
            await asyncio.sleep(0.01)
            listed = await client.list_tasks(ListTasksRequest())
            working = [t.id for t in listed.tasks if t.status.state == TaskState.TASK_STATE_WORKING]
        [task_id] = working
        owner = await lease.owner_of(task_id)
        await asyncio.sleep(1.2)
        renewed_owner = await lease.owner_of(task_id)
        month.gate.set()
        events = await running

    assert owner is not None
    assert renewed_owner == owner
    assert states(events)[-1] == "TASK_STATE_COMPLETED"
    assert await lease.owner_of(task_id) is None


async def test_every_request_batch_and_pause_validates_against_the_pinned_contract_schemas(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)
    async with await a2a_client(app, sign()) as client:
        covered = await ask(client, COVERED)
        missing = await ask(client, UNCOVERED)
    async with await a2a_client(app, None) as anonymous:
        sign_in = await ask(anonymous, COVERED)

    for data in (COVERED, UNCOVERED, CONTINUE):
        validator("request.schema.json").validate(data)
    assert not validator("request.schema.json").is_valid({"month": "2026-9"})
    rows = validator("rows.schema.json")
    for update in artifact_updates(covered):
        for batch in get_data_parts(update.artifact.parts):
            rows.validate(batch)
    for paused in (missing, sign_in):
        validator("pause.schema.json").validate(pause_parts(paused)[1])


async def test_each_call_holds_its_lease_under_an_owner_of_its_own(tmp_path: Path) -> None:
    lease = InMemoryLease(60)
    month = GatedMonth()
    async with await a2a_client(make_app(tmp_path, monthly=month, lease=lease), sign()) as client:
        running = [asyncio.create_task(ask(client, COVERED)) for _ in range(2)]
        working: list[str] = []
        while len(working) < 2:
            await asyncio.sleep(0.01)
            listed = await client.list_tasks(ListTasksRequest())
            working = [t.id for t in listed.tasks if t.status.state == TaskState.TASK_STATE_WORKING]
        owners = {await lease.owner_of(task_id) for task_id in working}
        month.gate.set()
        await asyncio.gather(*running)

    assert len(owners) == 2
    assert None not in owners


class PauseThenGatedMonth(GatedMonth):
    """The first fetch finds no statement; later ones signal they started and wait for the gate."""

    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self._fetches = 0

    async def fetch(self, person: str, month: str) -> list[TransactionRow]:
        self._fetches += 1
        if self._fetches == 1:
            raise StatementMissing(month)
        self.started.set()
        return await super().fetch(person, month)


class HeldAtRenewLease(InMemoryLease):
    """Holds the first renewal, the executor's check before WORKING, until the test opens it."""

    def __init__(self) -> None:
        super().__init__(60)
        self.renewing = asyncio.Event()
        self.gate = asyncio.Event()

    async def renew(self, task_id: str, owner: str) -> bool:
        self.renewing.set()
        await self.gate.wait()
        return await super().renew(task_id, owner)


async def test_a_continue_whose_caller_leaves_keeps_its_lease_while_the_task_runs(
    tmp_path: Path,
) -> None:
    """Drives the handler directly: the caller leaves while the executor runs but before the
    stream's first event."""
    lease = HeldAtRenewLease()
    month = PauseThenGatedMonth()
    executor = CardAgentExecutor(month, lease, 60)
    handler = CardRequestHandler(
        executor, InMemoryTaskStore(), build_agent_card(make_settings(tmp_path)), lease, "replica"
    )

    paused = [event async for event in handler.on_message_send_stream(request(COVERED), call())]
    task_id = paused[0].id
    stream = handler.on_message_send_stream(request(CONTINUE, task_id=task_id), call())
    first_event = asyncio.create_task(anext(stream))
    await asyncio.wait_for(lease.renewing.wait(), 5)
    first_event.cancel()
    [left] = await asyncio.gather(first_event, return_exceptions=True)
    lease.gate.set()
    await asyncio.wait_for(month.started.wait(), 5)
    held_while_running = await lease.owner_of(task_id)
    month.gate.set()
    await asyncio.wait_for(released(lease, task_id), 5)
    await handler.aclose()

    assert isinstance(left, asyncio.CancelledError | StopAsyncIteration), "no event came"
    assert held_while_running is not None


async def released(lease: InMemoryLease, task_id: str) -> None:
    while await lease.owner_of(task_id) is not None:
        await asyncio.sleep(0.01)


def call() -> ServerCallContext:
    context = ServerCallContext(user=CallerUser(CALLER))
    context.state.update(
        {CALLER_STATE_KEY: None, PERSON_KEY: VerifiedPerson(PERSON, None), AUTH_FAILURE_KEY: None}
    )
    return context


class LapsedLease(InMemoryLease):
    """The first renewal finds the lease gone: lapsed (dropped) or taken by another call (kept)."""

    def __init__(self, taken: bool) -> None:
        super().__init__(60)
        self._taken = taken
        self._renewals = 0

    async def renew(self, task_id: str, owner: str) -> bool:
        self._renewals += 1
        if self._renewals > 1:
            return await super().renew(task_id, owner)
        if not self._taken:
            await self.release(task_id, owner)
        return False


async def paused_then_continued(
    tmp_path: Path, lease: InMemoryLease
) -> tuple[Task, list[StreamResponse], Task]:
    month = PauseThenGatedMonth()
    month.gate.set()
    async with await a2a_client(make_app(tmp_path, monthly=month, lease=lease), sign()) as client:
        paused = await ask(client, COVERED)
        task_id = ids(paused)["task_id"]
        before = await client.get_task(GetTaskRequest(id=task_id))
        continued = await ask(client, CONTINUE, **ids(paused))
        after = await client.get_task(GetTaskRequest(id=task_id))
    return before, continued, after


async def test_a_continue_whose_lease_lapsed_takes_it_again_and_completes(tmp_path: Path) -> None:
    _, continued, after = await paused_then_continued(tmp_path, LapsedLease(taken=False))

    assert states(continued)[-1] == "TASK_STATE_COMPLETED"
    assert after.status.state == TaskState.TASK_STATE_COMPLETED


async def test_a_continue_whose_lease_another_call_holds_leaves_the_task_untouched(
    tmp_path: Path,
) -> None:
    before, continued, after = await paused_then_continued(tmp_path, LapsedLease(taken=True))

    assert states(continued) == []
    assert after == before
    assert after.status.state == TaskState.TASK_STATE_INPUT_REQUIRED
