"""Runtime configuration for one pool server, read once from the environment."""

from __future__ import annotations

import ipaddress
import os
import re
from dataclasses import dataclass

_SERVER_NAME = re.compile(r"[a-z](?:[-a-z0-9]{0,61}[a-z0-9])?", re.ASCII)
_SECRET_NAME = re.compile(r"projects/[a-z0-9-]+/secrets/[A-Za-z0-9_-]+", re.ASCII)


class ConfigError(ValueError):
    """The server cannot start with this configuration."""


@dataclass(frozen=True)
class Config:
    """Everything one pool server needs; nothing here is secret."""

    portal_url: str
    control_audience: str
    server_secret: str
    server_name: str
    tunnel_network: ipaddress.IPv4Network
    max_clients: int
    health_port: int
    runtime_dir: str


def _require(name: str) -> str:
    """Return a non-empty environment value or fail closed."""
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"{name} is required")
    return value


def load_config() -> Config:
    """Read and validate the server configuration, failing closed on any defect."""
    portal_url = _require("PORTAL_URL").rstrip("/")
    if not re.fullmatch(r"https://[A-Za-z0-9.-]+", portal_url):
        raise ConfigError("PORTAL_URL must be an https origin")
    server_secret = _require("SERVER_SECRET")
    if not _SECRET_NAME.fullmatch(server_secret):
        raise ConfigError("SERVER_SECRET must name a Secret Manager secret")
    server_name = _require("SERVER_NAME")
    if not _SERVER_NAME.fullmatch(server_name):
        raise ConfigError("SERVER_NAME must be the Compute Engine instance name")
    network = ipaddress.ip_network(_require("TUNNEL_NETWORK"), strict=True)
    if not isinstance(network, ipaddress.IPv4Network) or not 16 <= network.prefixlen <= 24:
        raise ConfigError("TUNNEL_NETWORK must be an IPv4 network between /16 and /24")
    max_clients = int(os.environ.get("MAX_CLIENTS", "250"))
    if not 1 <= max_clients <= network.num_addresses - 3:
        raise ConfigError("MAX_CLIENTS must fit inside TUNNEL_NETWORK")
    return Config(
        portal_url=portal_url,
        control_audience=_require("CONTROL_AUDIENCE"),
        server_secret=server_secret,
        server_name=server_name,
        tunnel_network=network,
        max_clients=max_clients,
        health_port=int(os.environ.get("HEALTH_PORT", "8080")),
        runtime_dir=os.environ.get("RUNTIME_DIR", "/run/openvpn"),
    )
