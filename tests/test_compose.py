"""Checks how docker-compose.yml and docker-compose.ec2.yml wire Redis, the replicas and the edge.

Only the edge publishes a port. The replicas receive only the keys the agent reads, learn the
paths inside the container from compose rather than the host forms of the settings files, and
get the callers registry as content compose copies in, never as a bind mount, so the same file
works against the EC2 instance's daemon. On the instance every image this repo builds carries the
:ec2 tag deploy.sh --ec2 loads, for the instance's ARM processor.
"""

from pathlib import Path
from typing import Any

import yaml

from calagent.platform.config import Settings

ROOT = Path(__file__).resolve().parents[1]
# Set by the Dockerfile's ENV to the image's own copy of the page; a host path would replace it.
IMAGE_SET_KEYS = {"STATIC_DIR"}


class _ComposeLoader(yaml.SafeLoader):
    """Reads compose's merge tags, !reset and !override, as the plain value they carry."""


def _tagged(loader: yaml.SafeLoader, node: yaml.Node) -> Any:
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    value = loader.construct_scalar(node)  # type: ignore[arg-type]
    return None if value in ("", "null", "~") else value


for _tag in ("!reset", "!override"):
    _ComposeLoader.add_constructor(_tag, _tagged)


def _load(name: str) -> dict[str, Any]:
    return yaml.load((ROOT / name).read_text(encoding="utf-8"), Loader=_ComposeLoader)


COMPOSE = _load("docker-compose.yml")
SERVICES = COMPOSE["services"]
EC2 = _load("docker-compose.ec2.yml")["services"]


def test_only_the_edge_publishes_a_port_on_the_loopback_interface() -> None:
    publishing = {name: spec["ports"] for name, spec in SERVICES.items() if "ports" in spec}
    assert publishing == {"edge": ["127.0.0.1:${EDGE_HOST_PORT:?set in stack-params.sh}:8030"]}


def test_each_replica_receives_only_the_keys_the_agent_reads() -> None:
    assert not [name for name, spec in SERVICES.items() if "env_file" in spec]
    settings_keys = {name.upper() for name in Settings.model_fields}
    assert set(SERVICES["cal-agent"]["environment"]) == settings_keys - IMAGE_SET_KEYS


def test_the_paths_inside_the_container_replace_the_host_forms() -> None:
    environment = SERVICES["cal-agent"]["environment"]
    assert environment["STATEMENTS_DIR"] == "/statements"
    assert environment["A2A_CALLERS_FILE"] == "/allowed-callers.yaml"
    assert environment["TASKS_REDIS_URL"] == "redis://redis:6379/0"


def test_the_callers_registry_is_copied_in_and_labels_its_digest() -> None:
    agent = SERVICES["cal-agent"]
    assert agent["secrets"] == [{"source": "allowed-callers", "target": "/allowed-callers.yaml"}]
    assert COMPOSE["secrets"]["allowed-callers"] == {"environment": "A2A_CALLERS_YAML"}
    assert "A2A_CALLERS_DIGEST" in agent["labels"]["cal-agent.callers-digest"]
    assert not [mount for mount in agent["volumes"] if "allowed-callers" in mount]


def test_the_edge_bakes_its_configuration_into_its_image() -> None:
    edge = SERVICES["edge"]
    assert edge["build"] == "nginx"
    assert "volumes" not in edge
    dockerfile = (ROOT / "nginx" / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY default.conf /etc/nginx/conf.d/default.conf" in dockerfile


def test_every_image_built_here_is_tagged_for_the_instance() -> None:
    built = {name for name, spec in SERVICES.items() if "build" in spec}
    assert built == {"cal-agent", "edge"}
    for name in built:
        assert EC2[name]["image"].endswith(":ec2"), name
        assert EC2[name]["platform"] == "linux/arm64", name


def test_every_service_restarts_with_the_instance() -> None:
    assert set(EC2) == set(SERVICES)
    for name, spec in EC2.items():
        assert spec["restart"] == "unless-stopped", name


def test_on_the_instance_the_statements_live_in_a_volume_owned_by_the_image_user() -> None:
    agent = EC2["cal-agent"]
    assert agent["volumes"] == ["cal_statements:/statements"]
    assert agent["user"] is None
    assert agent["environment"] == {"AGENT_URL": "${EC2_URL:?set by scripts/lib/ec2.sh}"}
    assert "ports" not in agent and "ports" not in EC2["redis"]
