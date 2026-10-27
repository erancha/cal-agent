import importlib

PACKAGES = [
    "calagent",
    "calagent.domain",
    "calagent.ports",
    "calagent.application",
    "calagent.adapters",
    "calagent.platform",
]


def test_package_imports() -> None:
    for package in PACKAGES:
        importlib.import_module(package)
