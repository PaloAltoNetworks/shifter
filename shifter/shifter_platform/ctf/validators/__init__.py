"""CTF Programmable Flag Validators.

Provides a registry of named validator functions for programmable flag types,
and an HTTP validation helper for HTTP flag types.

Validators are Python callables with the signature:
    (submitted_flag: str, params: dict[str, Any]) -> bool

The implementation is split across private submodules (``_ssrf``,
``_registry``, ``_http``) and re-exported here so callers continue to use
``from ctf.validators import X`` / ``from ctf import validators``.

The re-exports also rebind names that tests historically patch or import at
``ctf.validators.<name>`` (``socket``, ``_build_https_connection``, the
registry internals, and the SSRF/HTTP helper functions) so existing
``unittest.mock.patch`` targets and direct imports still work.

PATCH LOCALITY: ``_http.py`` never binds ``_build_https_connection`` into
its own module namespace at import time. Its one internal call site
(``_try_one_address``) instead resolves it through this package at call
time (``from ctf import validators as _v``, then ``_v._build_https_connection(...)``),
so a ``patch("ctf.validators._build_https_connection")`` mutates the single
attribute that call site actually looks up when it runs.

``socket`` is imported here (in addition to ``_ssrf.py``, which owns the
DNS/connect calls) purely so ``patch("ctf.validators.socket.<name>")``
keeps resolving: both names are bound to the same stdlib ``socket``
module object, so patching either mutates the real module globally.

All other cross-submodule calls (``_http`` -> ``_ssrf`` for
``_BLOCKED_HOSTNAMES`` / ``_BlockedDestinationError`` / ``_is_blocked_address``
/ ``_resolve_and_validate`` / ``_safe_parse_url``) are plain direct imports:
none of those names are patched at the package path, so no call-time
indirection is required.
"""

from __future__ import annotations

# Imported (not just used by submodules) so ``patch("ctf.validators.socket.X")``
# resolves: it is the same module object ``_ssrf.py`` calls into. See the
# PATCH LOCALITY note above.
import socket

from ._http import (
    DEFAULT_HTTP_TIMEOUT,
    MAX_HTTP_TIMEOUT,
    _build_request,
    _coerce_headers,
    _coerce_method,
    _coerce_timeout,
    _has_header_ci,
    _parse_response,
    _request_target,
    _resolve_target,
    _send_validation_request,
    _try_one_address,
    validate_http,
)
from ._registry import (
    _VALIDATORS,
    ValidatorFunc,
    _always_true,
    _contains_substring,
    get_validator,
    list_validators,
    register_validator,
)
from ._ssrf import (
    _BLOCKED_HOSTNAMES,
    _BlockedDestinationError,
    _build_https_connection,
    _is_blocked_address,
    _PinnedHTTPSConnection,
    _resolve_and_validate,
    _safe_parse_url,
    is_blocked_url,
)

__all__ = (
    "DEFAULT_HTTP_TIMEOUT",
    "MAX_HTTP_TIMEOUT",
    "_BLOCKED_HOSTNAMES",
    "_VALIDATORS",
    "ValidatorFunc",
    "_BlockedDestinationError",
    "_PinnedHTTPSConnection",
    "_always_true",
    "_build_https_connection",
    "_build_request",
    "_coerce_headers",
    "_coerce_method",
    "_coerce_timeout",
    "_contains_substring",
    "_has_header_ci",
    "_is_blocked_address",
    "_parse_response",
    "_request_target",
    "_resolve_and_validate",
    "_resolve_target",
    "_safe_parse_url",
    "_send_validation_request",
    "_try_one_address",
    "get_validator",
    "is_blocked_url",
    "list_validators",
    "register_validator",
    "socket",
    "validate_http",
)
