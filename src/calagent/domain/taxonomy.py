"""The fourteen spending categories of the monthly-transactions contract, in contract order."""

TAXONOMY: tuple[str, ...] = (
    "groceries",
    "dining",
    "transport",
    "utilities",
    "housing",
    "health",
    "insurance",
    "education",
    "shopping",
    "entertainment",
    "travel",
    "gifts",
    "other",
    "uncategorized",
)

UNCATEGORIZED = "uncategorized"


def require_category(value: str) -> str:
    if value not in TAXONOMY:
        raise ValueError(f"{value!r} is not a category; the categories are {', '.join(TAXONOMY)}")
    return value
