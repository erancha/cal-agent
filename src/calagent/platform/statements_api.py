"""The statements page and the HTTP API behind it: a signed-in person lists, uploads and deletes
their own Cal statement files.

Core building blocks:
- add_statements_routes: the page, the auth config the page reads, and the three statements routes
- ApiProblem: a refusal answered as a problem document whose detail names the cause
- _person: the person the bearer token was issued to for the page's own client; with
  authentication off every request is for the person anonymous
- _read_file: the multipart upload read through a byte-counting receive, so an oversized body is
  cut off while it arrives
"""

from collections.abc import MutableMapping
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.types import Message

from calagent.domain.errors import InvalidTokenError, StatementError, UploadRefused
from calagent.platform.a2a.context import ANONYMOUS, bearer_token
from calagent.platform.a2a.pause import PAGE_PATH
from calagent.ports.statements import StatementSource, StoredFile
from calagent.ports.tokens import TokenVerifier

UPLOAD_LIMIT_MB = 5
UPLOAD_LIMIT_BYTES = UPLOAD_LIMIT_MB * 1024 * 1024
# Multipart framing around the file: boundaries, part headers and the file name.
_BODY_OVERHEAD_BYTES = 64 * 1024
_PROBLEM_TYPE = "application/problem+json"

_Headers = MutableMapping[str, str]


class ApiProblem(Exception):
    def __init__(self, status: int, title: str, detail: str, headers: _Headers | None = None):
        super().__init__(detail)
        self.status = status
        self.title = title
        self.detail = detail
        self.headers = headers


class _BodyTooLarge(Exception):
    pass


def add_statements_routes(
    app: FastAPI,
    source: StatementSource,
    verifier: TokenVerifier | None,
    client_id: str | None,
    page_path: Path,
) -> None:
    def person_of(request: Request) -> str:
        return _person(request, verifier, client_id)

    @app.exception_handler(ApiProblem)
    async def problem(_: Request, failure: ApiProblem) -> Response:
        return _problem_response(failure.status, failure.title, failure.detail, failure.headers)

    @app.exception_handler(StatementError)
    async def unreadable(_: Request, failure: StatementError) -> Response:
        return _problem_response(400, "Bad Request", str(failure))

    @app.get(PAGE_PATH, include_in_schema=False)
    async def page() -> FileResponse:
        return FileResponse(page_path, media_type="text/html")

    @app.get("/api/auth/config")
    async def auth_config() -> dict[str, str | None]:
        return {"clientId": client_id if verifier is not None else None}

    @app.get("/api/statements")
    async def list_statements(request: Request) -> list[dict[str, Any]]:
        stored = await run_in_threadpool(source.list, person_of(request))
        return [_json(item) for item in stored]

    @app.post("/api/statements", status_code=201)
    async def add_statement(request: Request) -> dict[str, Any]:
        person = person_of(request)
        data = await _read_file(request)
        try:
            stored = await run_in_threadpool(source.store, person, data)
        except UploadRefused as refusal:
            raise ApiProblem(400, "Bad Request", str(refusal)) from refusal
        return _json(stored)

    @app.delete("/api/statements/{file_name:path}", status_code=204)
    async def delete_statement(request: Request, file_name: str) -> Response:
        try:
            await run_in_threadpool(source.delete, person_of(request), file_name)
        except UploadRefused as refusal:
            raise ApiProblem(400, "Bad Request", str(refusal)) from refusal
        return Response(status_code=204)


def _person(request: Request, verifier: TokenVerifier | None, client_id: str | None) -> str:
    if verifier is None:
        return ANONYMOUS
    assert client_id is not None
    try:
        token = bearer_token(request.headers.get("authorization"))
        return verifier.verify(token, client_id).sub
    except InvalidTokenError as failure:
        raise ApiProblem(
            401,
            "Unauthorized",
            f"Sign in with Google to see your statements: {failure.cause}",
            {"WWW-Authenticate": "Bearer"},
        ) from failure


async def _read_file(request: Request) -> bytes:
    too_large = ApiProblem(
        413,
        "Content Too Large",
        f"The file is larger than the {UPLOAD_LIMIT_MB} MB upload limit",
    )
    limit = UPLOAD_LIMIT_BYTES + _BODY_OVERHEAD_BYTES
    declared = request.headers.get("content-length")
    if declared is not None:
        if not declared.isascii() or not declared.isdigit():
            raise ApiProblem(400, "Bad Request", f"the Content-Length {declared!r} is not a number")
        if int(declared) > limit:
            raise too_large
    received = 0

    async def counting_receive() -> Message:
        nonlocal received
        message = await request.receive()
        received += len(message.get("body", b""))
        if received > limit:
            raise _BodyTooLarge()
        return message

    try:
        form = await Request(request.scope, counting_receive).form()
    except _BodyTooLarge as failure:
        raise too_large from failure
    part = form.get("file")
    if not isinstance(part, UploadFile):
        raise ApiProblem(400, "Bad Request", "the request has no file in the multipart part 'file'")
    if part.size is not None and part.size > UPLOAD_LIMIT_BYTES:
        raise too_large
    return await part.read()


def _json(stored: StoredFile) -> dict[str, Any]:
    return {
        "fileName": stored.file_name,
        "sizeBytes": stored.size_bytes,
        "modified": stored.modified.isoformat(),
    }


def _problem_response(
    status: int, title: str, detail: str, headers: _Headers | None = None
) -> JSONResponse:
    return JSONResponse(
        {"type": "about:blank", "title": title, "status": status, "detail": detail},
        status_code=status,
        media_type=_PROBLEM_TYPE,
        headers=headers,
    )
