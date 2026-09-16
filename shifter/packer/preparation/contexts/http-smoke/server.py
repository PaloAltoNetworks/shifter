"""Small dependency-free service used to qualify prepared-image boot behavior."""

from __future__ import annotations

import argparse
import json
import re
from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    """Answer a bounded fresh challenge without serving files or logging URLs."""

    def do_GET(self) -> None:
        match = re.fullmatch(r"/health/([a-zA-Z0-9-]{1,64})", self.path)
        if match is None:
            self.send_error(404)
            return
        body = json.dumps({"service": "shifter-http-smoke/v1", "nonce": match[1]}, sort_keys=True).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        """The specimen needs no access logs containing caller-selected paths."""


def main() -> None:
    """Run the specimen; the optional readiness file supports an isolated local test."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--bind", default="0.0.0.0")  # noqa: S104  # nosec B104
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    server = HTTPServer((args.bind, args.port), Handler)
    server.timeout = 10
    print(server.server_port, flush=True)  # noqa: T201 -- bounded readiness signal.
    # This deliberately qualifies a contained HTTP-only specimen. The isolated
    # guest carries only a fresh nonce and has no route to tenant workloads.
    server.serve_forever()  # NOSONAR


if __name__ == "__main__":
    main()
