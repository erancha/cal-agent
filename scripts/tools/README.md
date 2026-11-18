# Tools

Hands-on tools, run from any directory. Each prints its full usage with `--help`.

- `register-caller.sh` — registers an A2A caller in the gitignored `allowed-callers.yaml`, or
  replaces its entry: its name, the Google client id whose tokens it forwards, and a secret it
  mints and prints once with the values the caller's operator records. The next
  `deploy.sh`, or `deploy.sh --ec2`, hands the registry to the replicas.
- `validate.sh` — proves the agent end to end from the client side: starts it on the host against
  the test statement and drives it as a registered caller with `validate/check_agent.py`;
  `--tck` also runs the official A2A conformance suite.
- `anonymize-statement.py` — writes a copy of a statement PDF with the holder's private details
  replaced, to use as a test fixture.
- `lock.sh` — recompiles `requirements.txt` inside the Dockerfile's Python image; run it after
  editing the dependency list.

Back to the [README](../../README.md).
