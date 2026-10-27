# Categorizer

How each row gets a category from the shared taxonomy and a confidence, `high`, `medium` or `low`.
Amounts and dates never pass through a model; only the category and the display name do.

## Merchants, not rows

A month repeats merchants, and a merchant's category does not change between rows, so the agent
categorizes merchants. Each row's merchant string is reduced to a key: lower case, spaces
collapsed, trailing branch numbers and company forms such as `בע"מ` or `ltd` dropped. Only
merchants without a remembered decision go to the model, in batches of `CATEGORIZER_BATCH_SIZE`,
each merchant once however many rows it has.

The model scores each answer between 0 and 1. From `CATEGORIZER_HIGH_CONFIDENCE` up the row is
`high`, from `CATEGORIZER_MEDIUM_CONFIDENCE` up `medium`, below that `low`, and a `low` row keeps
the model's category as a guess the caller can confirm or correct. An answer outside the taxonomy
or the score range becomes `uncategorized` with `low` confidence; a model that answers a different
number of merchants than it was asked fails the task.

## The merchant memory

Every usable decision, the display name, category and confidence level, is remembered per person,
so a month asked for again, or a merchant met again next month, costs no model call. The memory
lives in Redis when the replicas share it (`TASKS_REDIS_URL`), as one hash per person with no
expiry, so a merchant one replica has decided costs no other replica, and no restart, a model call.
Without Redis it lives in the process.

A decision is remembered under a digest of three things: the merchant key, the sector label the
statement prints beside it, and a digest of the taxonomy with its category guides. A merchant met
under another sector is asked about again, since the sector is part of what the model judged, and
a changed category list or guide makes every remembered decision stale, so the model is asked
again under the new one.

An answer outside the taxonomy or the score range is not remembered: the row is `uncategorized`
for this request, and the next request asks the model again, so one bad answer never sticks.

## The prompt

Each batch is one structured-output call with the taxonomy and the raw merchant strings, each beside
the sector label the statement prints for it, such as `[sector: מסעדות]`. The model answers per
merchant with the raw string echoed, a display name, a category and a score. The prompt is shaped by
what goes wrong without it:

- **The sector is the issuer's own hint** about the business, so the model leans on it where the
  merchant string says little, such as a person's name billed under a medical sector.
- **A category is what the money buys, not how it is paid.** Each category carries a guide to the
  merchants it holds, so a gym paid by standing order is health and a streaming service
  entertainment.
- **No judging a shop by a generic word in its name**, and `uncategorized` rather than a guess.
- **The display name keeps the statement's language**, so a Hebrew merchant is never shown in
  English. It stays short when the brand explains itself (`Netflix`, `סלקום`) and keeps the words
  that say what the business does when it does not (`הראל ביטוח בריאות`).

## Providers

`LLM_MODEL` is `anthropic:<model>` or `openai:<model>`, with `LLM_API_KEY` that provider's key. It
has no default, so every deployment names its model. The answer's shape is enforced by the
provider: Anthropic through a forced tool call whose input schema is the answer list, OpenAI
through strict JSON-schema structured output, the same schema for both, with the category limited
to the taxonomy. Both clients are asynchronous, so a replica keeps serving other streams while one
task waits for the model.

Claude may reason before it answers, and the reasoning counts against the call's output limit, so
the Anthropic limit is 16384 tokens: a smaller one can run out on one batch of a few dozen
merchants. A reply cut short, a refusal, or an answer in another shape fails the task, naming what
the model did.

`LLM_MODEL=keyword` replaces the model with a fixed keyword table, so tests run without a model or
key. The table knows every merchant of the test statement but one, so a test review always has one
merchant for a person to categorize.
