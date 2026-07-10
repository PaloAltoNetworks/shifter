"""SPA host view for the Risk Register workspace (#1302, ADR-029 / #1300).

When ``settings.RISK_REGISTER_SPA_ENABLED`` is on, the GET page paths under
``/risk-register/`` are served by this single host view instead of the Django
templates (``risk_register.urls`` wires it). It renders the minimal SPA shell
(a mount node plus the built Vite entry/CSS resolved through the WhiteNoise
manifest) and primes the CSRF cookie so the SPA's first unsafe API call has a
token.

Authorization is intentionally thin here: the view requires an authenticated
session (anonymous users redirect to the shared login), but risk-register group
access is *not* enforced at this layer. The shell is public, cacheable markup
that leaks nothing; the SPA renders its own access-denied state when the
authoritative ``/api/v1/`` endpoints return 403. This matches the #1301 design
("403 renders an access-denied workspace state").
"""

from __future__ import annotations

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_safe

from shared.spa import vite_asset_urls


@require_safe
@ensure_csrf_cookie
def risk_register_spa_host(request: HttpRequest, *args, **kwargs) -> HttpResponse:
    """Serve the Risk Register SPA shell for any GET page path under the prefix."""
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path(), login_url=settings.LOGIN_URL)
    assets = vite_asset_urls()
    return render(
        request,
        "spa/risk_register.html",
        {"spa_js": assets["js"], "spa_css": assets["css"]},
    )
