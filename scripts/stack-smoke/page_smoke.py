#!/usr/bin/env python3
"""Authenticated page-render + static-asset smoke for the built image (#922).

Covers the range-independent half of the post-deploy functional gate (#923,
finding TEST-3): render the real authenticated pages from the *built* portal
image and assert their static assets resolve. This is the class of regression
that shipped to users in June (missing terminal sourcemaps / static assets):
invisible to the source-tree test estate, which never serves through whitenoise
off the image's collectstatic output.

For each page it GETs the URL with the smoke session cookie and an
``X-Forwarded-Proto: https`` header (mirroring the production ALB, so the
DEBUG=False image serves the page instead of issuing its HTTPS redirect), then:

* asserts the page returns 200 and non-empty HTML;
* GETs every *local* ``/static/...`` asset the page references and asserts 200
  (CDN/absolute URLs are skipped - the smoke must not depend on external hosts);
* for each referenced ``.js`` that declares a ``sourceMappingURL``, GETs the map
  and asserts 200 - the specific terminal-sourcemaps regression;
* asserts the locale-aware template chain ran (an ``<html ... lang=...>`` tag),
  a light i18n-wiring signal on top of the image's build-time compilemessages.

Range-dependent checks (live terminal data-exchange, Guacamole bootstrap, real
OIDC login) are deliberately out of scope; they need a live range / IdP and are
tracked separately. Stdlib only - no third-party deps, no secret values logged.
"""

from __future__ import annotations

import argparse
import re
import sys
import urllib.error
import urllib.request
from urllib.parse import urljoin

_STATIC_REF = re.compile(r'(?:src|href)="(/static/[^"]+)"')
_SOURCEMAP = re.compile(rb"//[#@]\s*sourceMappingURL=([^\s'\")]+)")
_LANG_ATTR = re.compile(r"<html[^>]*\blang=", re.IGNORECASE)


def _fetch(url: str, session: str, cookie_name: str) -> tuple[int, bytes]:
    req = urllib.request.Request(url)
    req.add_header("Cookie", f"{cookie_name}={session}")
    # Mirror the ALB's forwarded proto so SECURE_PROXY_SSL_HEADER marks the
    # request secure and the production image serves instead of 301-redirecting.
    req.add_header("X-Forwarded-Proto", "https")
    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310 - local loopback only
        return resp.status, resp.read()


def _check_asset(url: str, label: str, session: str, cookie_name: str, failures: list[str]) -> bytes:
    try:
        status, data = _fetch(url, session, cookie_name)
    except urllib.error.HTTPError as exc:
        failures.append(f"{label} -> HTTP {exc.code}")
        return b""
    except Exception as exc:  # noqa: BLE001 - any transport failure is a smoke failure
        failures.append(f"{label} -> {type(exc).__name__}")
        return b""
    if status != 200:
        failures.append(f"{label} -> HTTP {status}")
        return b""
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="e.g. http://127.0.0.1:18000")
    parser.add_argument("--session", required=True, help="Django session key")
    parser.add_argument("--paths", required=True, help="space-separated page paths")
    parser.add_argument("--cookie-name", default="sessionid")
    args = parser.parse_args()

    failures: list[str] = []
    saw_lang = False
    asset_count = 0

    for path in args.paths.split():
        page_url = urljoin(args.base, path)
        html_bytes = _check_asset(page_url, f"page {path}", args.session, args.cookie_name, failures)
        if not html_bytes:
            continue
        html = html_bytes.decode("utf-8", "replace")
        if not html.strip():
            failures.append(f"page {path} -> empty body")
            continue
        if _LANG_ATTR.search(html):
            saw_lang = True

        for ref in dict.fromkeys(_STATIC_REF.findall(html)):
            asset_url = urljoin(args.base, ref)
            data = _check_asset(asset_url, f"{path} asset {ref}", args.session, args.cookie_name, failures)
            asset_count += 1
            if not data or not ref.endswith(".js"):
                continue
            match = _SOURCEMAP.search(data)
            if not match:
                continue
            map_url = urljoin(asset_url, match.group(1).decode("ascii", "replace"))
            if not map_url.startswith(args.base):
                continue  # external sourcemap - out of scope
            _check_asset(map_url, f"{path} sourcemap {match.group(1).decode('ascii', 'replace')}",
                         args.session, args.cookie_name, failures)
            asset_count += 1

    if not saw_lang:
        failures.append("no <html lang=...> on any page (locale-aware template chain not exercised)")

    if failures:
        print("page-smoke: FAILED", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    print(f"page-smoke: OK ({len(args.paths.split())} pages, {asset_count} static assets/sourcemaps resolved)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
