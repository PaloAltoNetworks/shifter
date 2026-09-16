"""Independent functional probe for the contained HTTP image specimen."""

from __future__ import annotations

import http.client
import json
import re
import time


def probe_http(host: str, nonce: str, *, port: int = 8080, timeout: float = 60) -> bool:
    """Require the expected service and fresh challenge; never follow redirects."""
    if not re.fullmatch(r"[a-zA-Z0-9-]{1,64}", nonce) or not 0 < timeout <= 120:
        raise ValueError("invalid boot probe")
    deadline = time.monotonic() + timeout
    matched = False
    while time.monotonic() < deadline:
        connection = http.client.HTTPConnection(host, port, timeout=min(2, deadline - time.monotonic()))
        try:
            connection.request("GET", f"/health/{nonce}")
            response = connection.getresponse()
            body = response.read(513)
            if response.status != 200 or len(body) > 512:
                break
            matched = json.loads(body) == {"service": "shifter-http-smoke/v1", "nonce": nonce}
            break
        except (OSError, http.client.HTTPException):
            time.sleep(min(1, max(0, deadline - time.monotonic())))
        except ValueError:
            break
        finally:
            connection.close()
    return matched
