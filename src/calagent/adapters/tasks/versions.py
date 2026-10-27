"""Task versions as the integers the Redis adapters store: 0 is MISSING, the first write is 1."""

from a2a.server.cluster import TaskVersion


def version_number(version: TaskVersion) -> int:
    # The SDK keeps the wrapped value private; its own stores read it the same way.
    value = version._value
    if not isinstance(value, int):
        raise TypeError(f"the Redis task adapters use integer versions, got {version!r}")
    return value
