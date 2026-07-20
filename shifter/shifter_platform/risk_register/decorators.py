"""View decorators for risk register authorization."""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import TYPE_CHECKING

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.http import HttpResponse, HttpResponseForbidden

from risk_register.access import principal_has_risk_register_access

if TYPE_CHECKING:
    from django.http import HttpRequest


def risk_register_access_required(view_func: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
    """Require an authenticated user in an allowed Cognito group; return 403 otherwise."""

    @functools.wraps(view_func)
    def _wrapped(request: HttpRequest, *args, **kwargs) -> HttpResponse:
        """Enforce Cognito group membership before delegating to the view."""
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(), login_url=settings.LOGIN_URL)
        if not principal_has_risk_register_access(request):
            return HttpResponseForbidden("Forbidden")
        return view_func(request, *args, **kwargs)

    return _wrapped
