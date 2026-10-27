"""Failures the agent reports to callers; each message is a readable predicate or reason."""


class InvalidMonthError(ValueError):
    def __init__(self, text: str) -> None:
        super().__init__(f"{text!r} is not a billing month; expected YYYY-MM")


class StatementError(Exception):
    """A statement could not be read or looked up; the message is the predicate. The parser's
    messages are clauses about the file ("it has no pages") that StatementsFolder puts after its
    name."""


class StatementMissing(StatementError):
    def __init__(self, month: str) -> None:
        super().__init__(f"has no statement for {month}")


class InvalidTokenError(Exception):
    def __init__(self, cause: str) -> None:
        super().__init__(cause)
        self.cause = cause


class UploadRefused(Exception):
    """A statements-page request, an upload or a delete, was refused; the message is the
    reason."""


class CategorizerError(Exception):
    """The merchant categorizer failed; the message is a predicate."""


class ClassifierError(Exception):
    """The merchant classifier failed; the message is a predicate."""
