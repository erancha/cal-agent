# Codebase structure

The code is one package, `calagent` under `src/`, in layers: each layer imports only the layers
below it, and `lint-imports` enforces that from `pyproject.toml`, so the card work can change
without touching the protocol and the protocol without touching the card work.

| Package | Responsibility |
|---|---|
| `domain` | The values the rest is written in: the taxonomy, billing months, a parsed statement and its charges, the wire row and its 25-row batches, merchant keys and decisions, the categorizer's prompt text, and the failures a caller can read. |
| `ports` | What the card work depends on, as interfaces: the statements source and parser, the merchant classifier and memory, the token verifier and the task lease. |
| `application` | The skill's pipeline: a person's month as categorized rows, and the categorizer that consults the memory, batches unseen merchants to the classifier and maps scores to confidence. |
| `adapters` | The outside world: the Cal PDF parser, the statements folder, the Anthropic, OpenAI and keyword classifiers, the Google token verifier, the callers file, and the Redis task store, event stream, lease and merchant memory with in-memory twins of the lease and memory. |
| `platform` | Where it all meets the A2A SDK and FastAPI: settings, logging, the app and its startup, and in `platform/a2a` the Agent Card, the caller-secret middleware, the call-context builder, the admitting request handler, the executor, the pauses, the lease sweep and the conformance suite's scenario executor. The statements page's API sits beside them. |

`platform` composes everything; `application` builds on `ports` and `domain`; `adapters`
implement `ports` and import only `ports` and `domain`. `domain`, `ports` and `application` import
no framework: none of the A2A SDK, FastAPI, Starlette, Redis, pdfplumber, the model SDKs, httpx,
YAML, structlog or PyJWT. The A2A SDK reaches the card work only through the executor.
