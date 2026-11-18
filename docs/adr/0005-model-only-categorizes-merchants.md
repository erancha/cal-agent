# 0005. A language model only categorizes merchants, once per merchant and person

- Status: Accepted
- Date: 2026-10-27

## Context

Each row needs a category from the contract's closed taxonomy. A merchant string such as a shop
name or a person's name says little by itself, while the statement prints a sector label beside
it that hints at the business. A month repeats merchants, and a merchant's category does not
change between rows. Amounts and dates are printed in the PDF and must be exact. Anthropic and
OpenAI both offer models that answer in a schema the request fixes.

## Decision

- The categorizer reduces each merchant string to a key and asks a model only about merchants
  without a remembered decision, in batches, each with its sector label.
- The answer's shape is forced by the provider: a forced tool call on Anthropic, strict
  JSON-schema output on OpenAI, one schema for both, with the category limited to the taxonomy.
- The model scores each answer; two thresholds map the score to `high`, `medium` or `low`, and an
  answer outside the taxonomy or the score range is `uncategorized` and not remembered.
- Decisions are remembered per person, keyed by the merchant, its sector label and a digest of the
  taxonomy, so a changed taxonomy asks again.
- `LLM_MODEL` names the provider and model, with no default; `LLM_MODEL=keyword` replaces the
  model with a keyword table, so tests need no key.

## Consequences

- Amounts and dates never pass through a model; a month's numbers are as exact as the PDF.
- A repeated month, or a merchant met again, costs no model call on any replica.
- A model reply cut short, refused or in another shape fails the task, naming what happened.
- Changing provider is one setting, and both clients ship in the pinned dependencies.
