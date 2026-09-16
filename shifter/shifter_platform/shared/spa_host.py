"""Platform-wide SPA host view (#1369, ADR-013 / ADR-029 / #1300).

SPA-owned GET page paths are served by this single host view. It renders the
minimal shell (a mount node plus the
built Vite entry/CSS resolved through the WhiteNoise manifest) and primes the
CSRF cookie so the SPA's first unsafe API call has a token.

Authorization is intentionally thin here: the view requires an authenticated
session (anonymous users redirect to the shared login), but per-surface access
is *not* enforced at this layer. The shell is public, cacheable markup that
leaks nothing; the SPA renders its own access-denied state when the
authoritative ``/api/v1/`` endpoints return 403.
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
def platform_spa_host(request: HttpRequest, *args, **kwargs) -> HttpResponse:
    """Serve the platform SPA shell for any GET page path the shell owns."""
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path(), login_url=settings.LOGIN_URL)
    assets = vite_asset_urls()
    return render(
        request,
        "spa/platform.html",
        {"spa_js": assets["js"], "spa_css": assets["css"]},
    )
