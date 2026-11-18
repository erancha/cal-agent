#!/usr/bin/env bash
# Settings of this deployment that are its own and no secret. ./scripts/init-env.sh copies this
# file to lib/params.sh (gitignored); fill it in there. Every line is a plain export KEY="value":
# the scripts source the file, and the agent started on the host reads it too.

# Required: provider:model of the model that categorizes merchants, for the provider anthropic or
# openai. Classifying merchants with a usable confidence score wants the Haiku or mini tier, not
# the smallest one: anthropic:claude-haiku-5-5 or openai:gpt-5-mini. The value keyword selects a
# fixed keyword table that needs no API key; the tests and tools/validate.sh use it.
export LLM_MODEL="anthropic:claude-haiku-5-5"

# Required while access is required (A2A_AUTH_REQUIRED of stack-params.sh): this agent's own
# Google OAuth client id, a "Web application" client in its own Google Cloud project, with this
# agent's origin as an authorized JavaScript origin. The statements page signs in with it, and
# tokens sent to that page must be issued to it. Fill in by hand (docs/sign-in.md).
export AUTH_CLIENT_ID=""

# Optional: the address the README and NOTICE give for a commercial license. Tracked files may
# show this address; the pre-commit hook refuses any other address of this file.
export LICENSE_CONTACT=""

# deploy.sh --ec2 only: the stack whose EC2 instance this repo's stack runs on. Blank: this
# repo's stack is a host, with an instance of its own. The host stack of another Docker Compose
# repo (its EC2_STACK): this repo's stack is a guest on that instance, which is deployed first,
# from its own repo, in the account and region of aws-config.sh.
export EC2_HOST_STACK=""
