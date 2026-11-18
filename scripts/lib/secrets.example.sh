#!/usr/bin/env bash
# Secrets of the Compose stack. ./scripts/init-env.sh copies this file to lib/secrets.sh
# (gitignored); fill it in there and never commit it. Every line is a plain export KEY="value":
# the scripts source the file, and the agent started on the host reads it too. The secrets of the
# registered A2A callers live in allowed-callers.yaml, which scripts/tools/register-caller.sh
# writes.

# Required unless LLM_MODEL of params.sh is keyword: the API key of the provider LLM_MODEL names.
# Fill in by hand.
export LLM_API_KEY=""
