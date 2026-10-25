"""The OpenVPN server configuration and its credential files.

Options follow the OpenVPN 2.6 reference manual:

* ``tls-crypt``: only holders of a profile can reach the TLS handshake.
* ``remote-cert-tls client``, ``verify-client-cert require``,
  ``tls-version-min 1.2``, ``tls-cert-profile preferred``.
* AEAD data ciphers only.
* ``management-client-auth``: the controller decides every connection after
  OpenVPN verifies the certificate. ``auth-user-pass-optional`` lets
  certificate-only clients reach that decision; the controller identifies the
  client by its verified certificate common name only. ``username-as-common-name``
  must never be set: it would let a client choose its own identity.
* ``max-clients`` and ``connect-freq`` bound one server's load.
* ``keepalive 5 30``: clients ping every 5 seconds and reconnect after 30 seconds
  of silence, so an unplanned server loss costs about 30 seconds; a planned
  removal is announced at once by ``explicit-exit-notify``. Shorter timeouts
  would turn brief Wi-Fi loss into reconnects that drop open SSH/RDP sessions.
* No ``client-to-client``, no pushed default gateway: each client is pushed a
  route to its single target by the controller.
* No ``user``/``group``: the whole server already runs as the unprivileged
  ``shifter-vpn`` user with NET_ADMIN as its only capability (see the Dockerfile).
  ``management-client-user`` admits only that same user to the control socket.
"""

from __future__ import annotations

import json
import os
import pwd
from dataclasses import dataclass

from .config import Config

_MATERIAL_KEYS = frozenset({"ca", "certificate", "private_key", "tls_crypt"})


@dataclass(frozen=True)
class ServerPaths:
    """Where the rendered configuration and credentials live (a tmpfs)."""

    config: str
    management_socket: str


def write_material(runtime_dir: str, payload: str) -> None:
    """Write the server credentials with owner-only permissions."""
    material = json.loads(payload)
    if not isinstance(material, dict) or set(material) != _MATERIAL_KEYS:
        raise ValueError("server material has an invalid shape")
    os.makedirs(runtime_dir, mode=0o700, exist_ok=True)
    for name, key in (
        ("ca.crt", "ca"),
        ("server.crt", "certificate"),
        ("server.key", "private_key"),
        ("tls-crypt.key", "tls_crypt"),
    ):
        path = os.path.join(runtime_dir, name)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(str(material[key]))


def render(config: Config) -> str:
    """Return the server configuration text."""
    network = config.tunnel_network
    run = config.runtime_dir
    user = pwd.getpwuid(os.geteuid()).pw_name
    return f"""port 1194
proto udp4
dev tun0
dev-type tun
topology subnet
server {network.network_address} {network.netmask}
max-clients {config.max_clients}
connect-freq 20 10
keepalive 5 30
explicit-exit-notify 1
ca {run}/ca.crt
cert {run}/server.crt
key {run}/server.key
dh none
tls-crypt {run}/tls-crypt.key
tls-version-min 1.2
tls-cert-profile preferred
remote-cert-tls client
verify-client-cert require
data-ciphers AES-256-GCM:AES-128-GCM
auth SHA256
persist-key
persist-tun
management {run}/management.sock unix
management-client-user {user}
management-client-auth
auth-user-pass-optional
verb 3
"""


def write_config(config: Config) -> ServerPaths:
    """Render the configuration next to the credentials."""
    path = os.path.join(config.runtime_dir, "server.conf")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(render(config))
    return ServerPaths(config=path, management_socket=os.path.join(config.runtime_dir, "management.sock"))
