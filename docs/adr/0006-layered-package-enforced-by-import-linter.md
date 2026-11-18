# 0006. One package in layers, enforced by import-linter

- Status: Accepted
- Date: 2026-10-27

## Context

The agent joins two worlds that change for different reasons: the A2A protocol and its SDK on
one side, Cal's PDF layout and the categorizer on the other. The SDK's 1.x types are protobuf, and
its behavior around tasks and streams has rules of its own. The card pipeline should be testable
without the SDK, a web server or Redis, and a reader should find the protocol and the card work
apart.

## Decision

- One package, `calagent` under `src/`, in layers: `platform` over `application` over
  `ports` over `domain`.
- `adapters` implement `ports` and import only `ports` and `domain`.
- `domain`, `ports` and `application` import no framework: none of the A2A SDK, FastAPI,
  Starlette, Redis, pdfplumber, the model SDKs, httpx, YAML, structlog or PyJWT.
- The SDK reaches the card work only through the executor in `platform/a2a`.
- `lint-imports` checks these rules from `pyproject.toml` as part of `test.sh`.

## Consequences

- The month pipeline and the categorizer are tested with plain fakes of their ports.
- A protocol or SDK change touches `platform` only; a PDF layout change touches the parser only.
- A shortcut import across layers fails the quality gate instead of landing quietly.
