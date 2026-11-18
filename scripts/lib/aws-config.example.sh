#!/usr/bin/env bash
# AWS credentials and region the scripts source into their shell. ./scripts/init-env.sh copies
# this file to lib/aws-config.sh (gitignored); fill it in there and never commit it.

# Required: the access key id of an IAM user. A repo whose stacks join another repo's instance
# as guests (EC2_HOST_STACK set in stack-params.sh) uses the host repo's account.
export AWS_ACCESS_KEY_ID="<access-key-id>"

# Required: that access key's secret.
export AWS_SECRET_ACCESS_KEY="<secret-access-key>"

# Required: the region every stack of this repo deploys to. The host repo may pick any region,
# such as eu-central-1 or us-east-1; a guest repo uses the region of its host's stack.
export AWS_DEFAULT_REGION="<region>"
