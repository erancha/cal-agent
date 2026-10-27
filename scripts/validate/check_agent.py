#!/usr/bin/env python3
"""Proves a running cal-agent speaks the contract in docs/a2a-contract.md, from the client side.

The script plays a registered caller acting for one person: it signs that person's ID tokens with
the private key whose public half the agent was given, and sends each A2A call with the person's
token as the bearer and the caller's secret in X-Caller-Secret.

Checks, in order: the Agent Card advertises the skill, streaming and the two security schemes; a
streaming task for the covered month completes with the expected number of transactions; a task
for an uncovered month ends in input-required with the statement-missing reason naming the person;
continuing it asks again; cancelling the waiting task succeeds while cancelling the completed one
is refused; a call without the person's token, and one with a token issued to another client, end
in auth-required with the sign-in-required reason; a wrong secret is 401; the statements API
refuses a call without the person's token and lists their statement with it.

Exit status 0 when every check passes; the first failing check is printed and exits 1.
"""
import argparse
import asyncio
import sys
import time
from contextlib import aclosing

import httpx
import jwt
from a2a.client import A2ACardResolver, ClientConfig, ClientFactory
from a2a.helpers import get_data_parts, new_data_part, new_message
from a2a.types import CancelTaskRequest, Role, SendMessageRequest, TaskState
from a2a.utils.errors import TaskNotCancelableError

SKILL = "monthly-transactions"
SECRET_HEADER = "X-Caller-Secret"
PERSON = "1000"


def check(condition: bool, label: str) -> None:
    print(("PASS: " if condition else "FAIL: ") + label)
    if not condition:
        sys.exit(1)


# States after which the task produces no further events until the client acts.
STOP_STATES = {TaskState.TASK_STATE_COMPLETED, TaskState.TASK_STATE_FAILED,
               TaskState.TASK_STATE_CANCELED, TaskState.TASK_STATE_REJECTED,
               TaskState.TASK_STATE_INPUT_REQUIRED, TaskState.TASK_STATE_AUTH_REQUIRED}


def id_token(private_key: str, issuer: str, audience: str, sub: str = PERSON) -> str:
    now = int(time.time())
    claims = {"iss": issuer, "aud": audience, "sub": sub, "iat": now, "exp": now + 600,
              "email": f"{sub}@example.com", "name": f"Person {sub}"}
    return jwt.encode(claims, private_key, algorithm="RS256")


async def stream(client, message, context=None):
    """Collects (last status update, artifact rows) from one streamed request.

    Reading stops at the first final or interrupted status rather than relying on the server to
    end the stream there.
    """
    last_status = None
    rows = []
    events = client.send_message(SendMessageRequest(message=message), context=context)
    async with aclosing(events):
        async for chunk in events:
            if chunk.HasField("artifact_update"):
                for data in get_data_parts(chunk.artifact_update.artifact.parts):
                    rows.extend(data["transactions"])
            elif chunk.HasField("status_update"):
                last_status = chunk.status_update
                if last_status.status.state in STOP_STATES:
                    break
    return last_status, rows


def user_message(data, **ids):
    return new_message([new_data_part(data)], role=Role.ROLE_USER, **ids)


def reason_of(status) -> dict:
    parts = get_data_parts(status.status.message.parts)
    return next((d for d in parts if "reason" in d), {})


def card_schemes(card) -> tuple[bool, bool]:
    schemes = card.security_schemes
    oidc = any(s.HasField("open_id_connect_security_scheme") for s in schemes.values())
    api_key = any(s.HasField("api_key_security_scheme")
                  and s.api_key_security_scheme.name == SECRET_HEADER
                  and s.api_key_security_scheme.location.lower() == "header"
                  for s in schemes.values())
    return oidc, api_key


async def a2a_checks(args, private_key: str) -> None:
    caller_token = id_token(private_key, args.issuer, args.caller_client_id)
    headers = {"Authorization": f"Bearer {caller_token}", SECRET_HEADER: args.caller_secret}
    async with httpx.AsyncClient(headers=headers, timeout=60) as http:
        card = await A2ACardResolver(http, args.base_url).get_agent_card()
        check(any(s.id == SKILL for s in card.skills), f"card advertises {SKILL}")
        check(card.capabilities.streaming, "card advertises streaming")
        oidc, api_key = card_schemes(card)
        check(oidc, "card declares the person's token as an OpenID Connect scheme")
        check(api_key, f"card declares the caller's secret as an API key in {SECRET_HEADER}")
        client = ClientFactory(ClientConfig(streaming=True, httpx_client=http)).create(card)

        completed, rows = await stream(client, user_message({"month": args.covered}))
        check(completed is not None
              and completed.status.state == TaskState.TASK_STATE_COMPLETED,
              f"{args.covered} completes")
        check(len(rows) == args.count, f"{args.covered} streams {args.count} transactions")
        check(all(r["category"] for r in rows), "every transaction carries a category")

        waiting, _ = await stream(client, user_message({"month": args.uncovered}))
        check(waiting is not None
              and waiting.status.state == TaskState.TASK_STATE_INPUT_REQUIRED,
              f"{args.uncovered} asks for input")
        reason = reason_of(waiting)
        check(reason.get("reason") == "statement-missing", "reason is statement-missing")
        check(reason.get("user") == PERSON, "the request names the person it is for")

        resumed, _ = await stream(client, user_message(
            {"action": "continue"}, task_id=waiting.task_id, context_id=waiting.context_id))
        check(resumed is not None
              and resumed.status.state == TaskState.TASK_STATE_INPUT_REQUIRED,
              "continue without the file asks again")

        canceled = await client.cancel_task(CancelTaskRequest(id=waiting.task_id))
        check(canceled.status.state == TaskState.TASK_STATE_CANCELED,
              "cancel of the waiting task succeeds")

        try:
            await client.cancel_task(CancelTaskRequest(id=completed.task_id))
            refused = False
        except TaskNotCancelableError:
            refused = True
        check(refused, "cancel of the completed task is refused")

    page_token = id_token(private_key, args.issuer, args.page_client_id)
    for label, bearer in (("no person's token", None), ("a token for another client", page_token)):
        headers = {SECRET_HEADER: args.caller_secret}
        if bearer is not None:
            headers["Authorization"] = f"Bearer {bearer}"
        async with httpx.AsyncClient(headers=headers, timeout=60) as http:
            card = await A2ACardResolver(http, args.base_url).get_agent_card()
            client = ClientFactory(ClientConfig(streaming=True, httpx_client=http)).create(card)
            status, rows = await stream(client, user_message({"month": args.covered}))
            check(status is not None
                  and status.status.state == TaskState.TASK_STATE_AUTH_REQUIRED
                  and reason_of(status).get("reason") == "sign-in-required" and not rows,
                  f"{label} ends in auth-required with sign-in-required")

    wrong = {"Authorization": f"Bearer {caller_token}", SECRET_HEADER: "wrong",
             "A2A-Version": "1.0"}
    async with httpx.AsyncClient(headers=wrong, timeout=10) as http:
        r = await http.post(args.base_url + "/", json={"jsonrpc": "2.0", "id": 1,
                                                        "method": "GetTask",
                                                        "params": {"id": "x"}})
        check(r.status_code == 401 and r.headers.get("WWW-Authenticate") == SECRET_HEADER,
              "wrong secret is 401")


def statements_checks(args, private_key: str) -> None:
    config = httpx.get(args.base_url + "/api/auth/config", timeout=10)
    check(config.status_code == 200 and config.json() == {"clientId": args.page_client_id},
          "the auth config names the page's client")
    anonymous = httpx.get(args.base_url + "/api/statements", timeout=10)
    check(anonymous.status_code == 401, "the statements API refuses a call without a token")
    page_token = id_token(private_key, args.issuer, args.page_client_id)
    mine = httpx.get(args.base_url + "/api/statements", timeout=10,
                     headers={"Authorization": f"Bearer {page_token}"})
    check(mine.status_code == 200
          and [s["fileName"] for s in mine.json()] == [f"{args.covered}.pdf"],
          "the statements API lists the person's own statement")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("base_url")
    parser.add_argument("--private-key", required=True, help="PEM file that signs the tokens")
    parser.add_argument("--issuer", required=True)
    parser.add_argument("--caller-secret", required=True)
    parser.add_argument("--caller-client-id", required=True)
    parser.add_argument("--page-client-id", required=True)
    parser.add_argument("--covered", required=True, help="billing month with a statement")
    parser.add_argument("--count", required=True, type=int, help="its transaction count")
    parser.add_argument("--uncovered", required=True, help="billing month without one")
    args = parser.parse_args()
    with open(args.private_key, encoding="utf-8") as pem:
        private_key = pem.read()
    asyncio.run(a2a_checks(args, private_key))
    statements_checks(args, private_key)
    print("All checks passed.")


if __name__ == "__main__":
    main()
