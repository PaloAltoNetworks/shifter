"""Start one pool server: credentials, firewall, OpenVPN, then the controller loop.

Any failure of OpenVPN, the management connection or the controller ends the
process; the VM restarts the container, and clients reconnect to a healthy
server. A restarted controller starts with no sessions and a fresh ruleset.

On SIGTERM (``docker stop`` when the VM is replaced, scaled in or shut down)
the controller, which is PID 1, passes the signal to OpenVPN. OpenVPN's
``explicit-exit-notify`` then tells every client to reconnect at once, so a
planned removal costs participants seconds rather than a keepalive timeout.
"""

from __future__ import annotations

import logging
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable

from . import gcp
from .config import load_config
from .controller import Controller
from .firewall import Firewall
from .management import Management
from .portal import PortalClient
from .server_config import write_config, write_material

_OPENVPN = "/usr/sbin/openvpn"


_LOGGER = logging.getLogger("shifter_openvpn")


def _log(message: str) -> None:
    """Write one operational line to the container log."""
    _LOGGER.info(message)


def _wait_for_socket(path: str, process: subprocess.Popen[bytes], timeout: float = 30) -> None:
    """Wait for OpenVPN's management socket, failing if OpenVPN exits or stalls."""
    deadline = time.monotonic() + timeout
    while not os.path.exists(path):
        if process.poll() is not None or time.monotonic() > deadline:
            raise RuntimeError("OpenVPN did not open its management socket")
        time.sleep(0.2)


def _serve_health(port: int) -> None:
    """Accept and close TCP connections on the health port for the load balancer.

    The listener opens only once the server is ready and closes with the
    process, so a completed handshake is the health signal; no data is
    exchanged. It binds the container's own interface, which tunnel clients
    cannot reach (their input is dropped by the firewall).
    """
    address = socket.gethostbyname(socket.gethostname())
    with socket.create_server((address, port), backlog=64) as listener:
        while True:
            connection, _peer = listener.accept()
            connection.close()


def _forward_stop(process: subprocess.Popen[bytes], stopping: threading.Event) -> Callable[[int, object], None]:
    """Return a signal handler that asks OpenVPN to notify its clients and exit."""

    def handler(_signum: int, _frame: object) -> None:
        """Mark the stop as intended, then send OpenVPN SIGTERM."""
        stopping.set()
        process.terminate()

    return handler


def _watch_openvpn(process: subprocess.Popen[bytes], stopping: threading.Event) -> None:
    """End the server when OpenVPN exits: cleanly when asked to stop, as a failure otherwise."""
    process.wait()
    os._exit(0 if stopping.is_set() else 1)


def _heartbeat(controller: Controller) -> None:
    """Renew live sessions with the portal for the life of the process."""
    while True:
        time.sleep(controller.heartbeat())


def main() -> int:
    """Start the server; return only when the management connection closes."""
    logging.basicConfig(stream=sys.stdout, level=logging.INFO, format="%(asctime)s %(message)s")
    config = load_config()
    write_material(config.runtime_dir, gcp.read_secret(config.server_secret))
    paths = write_config(config)
    Firewall().install(config.tunnel_network)
    # Fixed argv with no shell; the only argument is the config path written above.
    process = subprocess.Popen([_OPENVPN, "--config", paths.config])  # noqa: S603
    _wait_for_socket(paths.management_socket, process)
    management = Management(paths.management_socket)
    portal = PortalClient(config.portal_url, config.control_audience, config.server_name, gcp.identity_token)
    controller = Controller(management, portal, Firewall(), log=_log)
    threading.Thread(target=_heartbeat, args=(controller,), daemon=True, name="heartbeat").start()
    stopping = threading.Event()
    for stop_signal in (signal.SIGTERM, signal.SIGINT):
        signal.signal(stop_signal, _forward_stop(process, stopping))
    threading.Thread(target=_watch_openvpn, args=(process, stopping), daemon=True, name="openvpn-watch").start()
    threading.Thread(target=_serve_health, args=(config.health_port,), daemon=True, name="health").start()
    _log(f"pool server {config.server_name} ready")
    while (event := management.events.get()) is not None:
        controller.handle(event)
    _log("management connection closed")
    return 1


if __name__ == "__main__":
    sys.exit(main())
