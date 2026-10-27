from pathlib import Path

import yaml

from calagent.platform.config import Settings


def test_env_example_documents_every_setting() -> None:
    text = Path(".env.example").read_text()
    undocumented = [name for name in Settings.model_fields if name.upper() not in text]
    assert undocumented == []


def test_only_the_edge_publishes_a_port() -> None:
    services = yaml.safe_load(Path("docker-compose.yml").read_text())["services"]
    publishing = [name for name, service in services.items() if "ports" in service]
    assert publishing == ["edge"]
