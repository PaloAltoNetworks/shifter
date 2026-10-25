"""Per-client forwarding policy with nftables, inside the server's network namespace.

Forwarding drops by default. Each authorized client gets set elements
``(tunnel address, target address, port)`` for its declared ports only, added
after OpenVPN reports the client's tunnel address and removed when it leaves.
Clients can never reach the server itself, each other, the metadata server, or
any other address. Client traffic leaves NATed to the server's address.
"""

from __future__ import annotations

import ipaddress
import subprocess
from collections.abc import Callable

TABLE = "shifter_vpn"
_NFT = "/usr/sbin/nft"


def base_ruleset(tunnel_network: ipaddress.IPv4Network, tunnel_device: str = "tun0") -> str:
    """Return the complete ruleset this server starts from (replacing any previous one)."""
    return f"""table inet {TABLE}
delete table inet {TABLE}
table inet {TABLE} {{
    set allowed {{
        type ipv4_addr . ipv4_addr . inet_service
    }}
    chain input {{
        type filter hook input priority filter; policy accept;
        iifname "{tunnel_device}" drop
    }}
    chain forward {{
        type filter hook forward priority filter; policy drop;
        ct state established,related accept
        iifname "{tunnel_device}" ct state new ip saddr . ip daddr . tcp dport @allowed accept
    }}
    chain postrouting {{
        type nat hook postrouting priority srcnat; policy accept;
        ip saddr {tunnel_network} oifname != "{tunnel_device}" masquerade
    }}
}}
"""


def _elements(client: str, target: str, ports: tuple[int, ...]) -> str:
    """Render validated set elements; addresses and ports never reach nft unchecked."""
    client_ip = ipaddress.IPv4Address(client)
    target_ip = ipaddress.IPv4Address(target)
    if not ports or any(isinstance(port, bool) or not 1 <= port <= 65535 for port in ports):
        raise ValueError("invalid port list")
    return ", ".join(f"{client_ip} . {target_ip} . {port}" for port in sorted(set(ports)))


def _nft(script: str) -> None:
    """Apply one nft script atomically."""
    # Fixed argv with no shell; the script on stdin is built from validated values.
    subprocess.run([_NFT, "-f", "-"], input=script, text=True, check=True, capture_output=True)  # noqa: S603


class Firewall:
    """Apply the base ruleset and per-client allowances through ``nft -f -``."""

    def __init__(self, runner: Callable[[str], None] = _nft) -> None:
        self._run = runner

    def install(self, tunnel_network: ipaddress.IPv4Network) -> None:
        self._run(base_ruleset(tunnel_network))

    def allow(self, client: str, target: str, ports: tuple[int, ...]) -> None:
        self._run(f"add element inet {TABLE} allowed {{ {_elements(client, target, ports)} }}\n")

    def revoke(self, client: str, target: str, ports: tuple[int, ...]) -> None:
        self._run(f"delete element inet {TABLE} allowed {{ {_elements(client, target, ports)} }}\n")
