from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from calagent.domain.errors import StatementError
from calagent.platform.app import build_app, default_parts
from calagent.ports.statements import StoredFile
from tests.auth_keys import CALLER_CLIENT_ID, OTHER_KEY, PAGE_CLIENT_ID, sign
from tests.platform.support import (
    FIXTURE,
    http_client,
    make_app,
    make_settings,
    statement_path,
)

API = "/api/statements"
LIMIT = 5 * 1024 * 1024


def page_client(tmp_path: Path) -> httpx.AsyncClient:
    """The page as person 1000, who holds no statements yet."""
    app = make_app(tmp_path)
    statement_path(tmp_path).unlink()
    return http_client(app, sign(aud=PAGE_CLIENT_ID), secret=None)


def pdf() -> dict[str, tuple[str, bytes, str]]:
    return {"file": ("anything.pdf", FIXTURE.read_bytes(), "application/pdf")}


async def test_list_without_a_token_is_401_with_a_bearer_challenge(tmp_path: Path) -> None:
    async with http_client(make_app(tmp_path), None, secret=None) as client:
        response = await client.get(API)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    body = response.json()
    assert body["type"] == "about:blank" and body["status"] == 401
    assert body["detail"].startswith("Sign in with Google to see your statements: ")


async def test_a_token_for_the_callers_client_is_refused(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    async with http_client(app, sign(aud=CALLER_CLIENT_ID), secret=None) as client:
        response = await client.get(API)
    assert response.status_code == 401


async def test_an_expired_or_forged_token_is_refused_with_its_cause(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    for token in (sign(aud=PAGE_CLIENT_ID, exp=1), sign(OTHER_KEY, aud=PAGE_CLIENT_ID)):
        async with http_client(app, token, secret=None) as client:
            response = await client.get(API)
        assert response.status_code == 401
        assert len(response.json()["detail"]) > len("Sign in with Google to see your statements: ")


async def test_upload_list_and_delete_a_statement(tmp_path: Path) -> None:
    async with page_client(tmp_path) as client:
        assert (await client.get(API)).json() == []
        created = await client.post(API, files=pdf())
        assert created.status_code == 201
        assert created.json()["fileName"] == "2026-10.pdf"
        [listed] = (await client.get(API)).json()
        assert listed == created.json()
        assert listed["sizeBytes"] == FIXTURE.stat().st_size
        assert (await client.delete(f"{API}/2026-10.pdf")).status_code == 204
        again = await client.delete(f"{API}/2026-10.pdf")
        assert again.status_code == 400
        assert "2026-10.pdf" in again.json()["detail"]


async def test_a_second_upload_for_a_month_is_400_naming_it(tmp_path: Path) -> None:
    async with page_client(tmp_path) as client:
        await client.post(API, files=pdf())
        response = await client.post(API, files=pdf())
    assert response.status_code == 400
    assert "2026-10" in response.json()["detail"]


async def test_a_file_that_is_not_a_pdf_is_400(tmp_path: Path) -> None:
    async with page_client(tmp_path) as client:
        response = await client.post(API, files={"file": ("a.pdf", b"hello", "application/pdf")})
    assert response.status_code == 400
    assert "not a PDF" in response.json()["detail"]


async def test_a_request_without_the_file_part_is_400(tmp_path: Path) -> None:
    async with page_client(tmp_path) as client:
        response = await client.post(API, files={"other": ("a.pdf", b"x", "application/pdf")})
    assert response.status_code == 400


async def test_one_byte_over_the_limit_is_413(tmp_path: Path) -> None:
    body = b"%PDF-" + b"0" * (LIMIT - 4)
    async with page_client(tmp_path) as client:
        response = await client.post(API, files={"file": ("a.pdf", body, "application/pdf")})
    assert response.status_code == 413
    assert response.json()["detail"] == "The file is larger than the 5 MB upload limit"


async def test_a_body_far_over_the_limit_is_cut_off_while_it_arrives(tmp_path: Path) -> None:
    opening = b'--x\r\nContent-Disposition: form-data; name="file"; filename="a.pdf"\r\n\r\n'
    chunk = b"0" * 65536
    sent = 0

    async def body() -> AsyncIterator[bytes]:
        nonlocal sent
        yield opening
        for _ in range(1600):
            sent += len(chunk)
            yield chunk

    async with page_client(tmp_path) as client:
        response = await client.post(
            API, content=body(), headers={"Content-Type": "multipart/form-data; boundary=x"}
        )
    assert response.status_code == 413
    assert sent < 10 * LIMIT


async def test_a_person_sees_and_deletes_only_their_own_folder(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    async with http_client(app, sign(aud=PAGE_CLIENT_ID, sub="2000"), secret=None) as other:
        assert (await other.get(API)).json() == []
        assert (await other.delete(f"{API}/2026-10.pdf")).status_code == 400
    assert statement_path(tmp_path).exists()


async def test_a_statement_failure_is_a_readable_problem(tmp_path: Path) -> None:
    class Failing:
        def list(self, person: str) -> list[StoredFile]:
            raise StatementError("could not read 2026-09.pdf: it has no pages")

    settings = make_settings(tmp_path)
    parts = default_parts(settings)
    app = build_app(settings, replace(parts, statements=Failing()))  # type: ignore[arg-type]
    async with http_client(app, sign(aud=PAGE_CLIENT_ID), secret=None) as client:
        response = await client.get(API)
    assert response.status_code == 400
    assert response.json()["detail"] == "could not read 2026-09.pdf: it has no pages"


async def test_the_api_acts_for_anonymous_with_authentication_off(tmp_path: Path) -> None:
    app = make_app(tmp_path, a2a_auth_required=False)
    async with http_client(app, None, secret=None) as client:
        assert (await client.get("/api/auth/config")).json() == {"clientId": None}
        assert (await client.get(API)).json() == []
        assert (await client.post(API, files=pdf())).status_code == 201
    assert (tmp_path / "statements" / "anonymous" / "2026-10.pdf").exists()


async def test_the_auth_config_names_the_pages_client(tmp_path: Path) -> None:
    async with http_client(make_app(tmp_path), None, secret=None) as client:
        response = await client.get("/api/auth/config")
    assert response.json() == {"clientId": PAGE_CLIENT_ID}


async def test_the_page_is_served_without_a_client_id(tmp_path: Path) -> None:
    async with http_client(make_app(tmp_path), None, secret=None) as client:
        response = await client.get("/statements.html")
    assert response.status_code == 200
    assert "Cal" in response.text
    assert ".apps.googleusercontent.com" not in response.text


def test_startup_refuses_a_static_folder_without_the_page(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="STATIC_DIR=.*nowhere.*statements.html"):
        make_app(tmp_path, static_dir=tmp_path / "nowhere")


async def test_a_content_length_that_is_not_a_number_is_a_400_problem(tmp_path: Path) -> None:
    async with page_client(tmp_path) as client:
        response = await client.post(
            API,
            content=b"x",
            headers={"Content-Type": "multipart/form-data; boundary=x", "Content-Length": "abc"},
        )
    assert response.status_code == 400
    assert "Content-Length" in response.json()["detail"]


async def test_a_traversal_name_deletes_nothing(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    async with http_client(app, sign(aud=PAGE_CLIENT_ID), secret=None) as client:
        encoded = await client.delete(f"{API}/..%2F2026-10.pdf")
        assert encoded.status_code == 400
        assert "no statement named" in encoded.json()["detail"]
        assert (await client.delete(f"{API}/../x.pdf")).status_code == 404
    assert statement_path(tmp_path).exists()


async def test_only_the_rpc_post_needs_the_callers_secret(tmp_path: Path) -> None:
    async with http_client(make_app(tmp_path), None, secret=None) as client:
        assert (await client.post("/", json={})).status_code == 401
        assert (await client.get("/api/auth/config")).status_code == 200
        assert (await client.get("/statements.html")).status_code == 200
