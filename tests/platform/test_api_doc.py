"""docs/api.md names every HTTP route the app declares, and no route it does not.

The router is the source of truth: each APIRoute's methods and path, read from the app at run
time through iter_route_contexts, which resolves the routers the app includes into the routes
they declare, HEAD and OPTIONS left out; the A2A SDK's routes are APIRoutes too. FastAPI's own
documentation routes are not APIRoutes, so they are not product routes and are not compared. The
document names a route in backticks as `METHOD /path`, the path exactly as the router declares
it. The fixture `app` is the only part of this file tied to this repository.
"""

import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute, iter_route_contexts

from tests.platform.support import make_app

HTTP_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
DOC_ROUTE = re.compile(r"`(" + "|".join(HTTP_METHODS) + r") (/[^`\s]*)`")
API_DOC = next(p for p in Path(__file__).resolve().parents if (p / "docs").is_dir()) / "docs/api.md"


@pytest.fixture
def app(tmp_path: Path) -> FastAPI:
    return make_app(tmp_path)


def declared_routes(app: FastAPI) -> set[str]:
    return {
        f"{method} {route.path}"
        for route in iter_route_contexts(app.routes)
        if isinstance(route.original_route, APIRoute)
        for method in route.original_route.methods
        if method in HTTP_METHODS
    }


def documented_routes(doc: str) -> set[str]:
    return {f"{m.group(1)} {m.group(2)}" for m in DOC_ROUTE.finditer(doc)}


def test_api_doc(app: FastAPI) -> None:
    declared = declared_routes(app)
    documented = documented_routes(API_DOC.read_text())
    problems = [f"undocumented in {API_DOC}: `{r}`" for r in sorted(declared - documented)]
    problems += [
        f"{API_DOC} names `{r}`, which the app does not declare"
        for r in sorted(documented - declared)
    ]
    assert not problems, "\n".join(problems)
