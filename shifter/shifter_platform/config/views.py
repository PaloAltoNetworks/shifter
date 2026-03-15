"""Simple views for the platform."""

import logging

from django.conf import settings
from django.contrib.auth import BACKEND_SESSION_KEY, logout
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_POST

from shared.auth import is_ctf_organizer, is_ctf_participant

logger = logging.getLogger(__name__)


def home(request):
    """Landing page - coming soon."""
    return render(request, "coming_soon.html")


@login_required
def dashboard_router(request):
    """Route authenticated users to the correct dashboard based on user type.

    - standard users -> Mission Control dashboard
    - ctf_organizer -> CTF Admin dashboard
    - ctf_participant -> Mission Control dashboard (with restricted nav)
    """
    if is_ctf_organizer(request.user):
        logger.debug("Routing organizer %s to Mission Control dashboard", request.user.email)
        return HttpResponseRedirect(reverse("mission_control:dashboard"))
    elif is_ctf_participant(request.user):
        logger.debug("Routing participant %s to Mission Control dashboard", request.user.email)
        return HttpResponseRedirect(reverse("mission_control:dashboard"))
    else:
        logger.debug("Routing standard user %s to Mission Control", request.user.email)
        return HttpResponseRedirect(reverse("mission_control:dashboard"))


@require_POST
def logout_view(request):
    """Log out the current user, routing to the correct logout mechanism.

    OIDC users (authenticated via ShifterOIDCBackend) get their Django
    session cleared and are redirected to Cognito's logout endpoint to
    also clear the identity provider session.

    All other users (magic-link CTF participants, dev-login) get a
    simple Django session logout and redirect to the landing page.
    """
    if not request.user.is_authenticated:
        return HttpResponseRedirect(settings.LOGOUT_REDIRECT_URL)

    backend = request.session.get(BACKEND_SESSION_KEY, "")
    email = request.user.email
    redirect_url = settings.LOGOUT_REDIRECT_URL

    if "OIDCAuthenticationBackend" in backend:
        # Build the Cognito logout URL before clearing the session,
        # since provider_logout_url needs the request for the redirect URI.
        logout_url_method = getattr(settings, "OIDC_OP_LOGOUT_URL_METHOD", "")
        if logout_url_method:
            from django.utils.module_loading import import_string

            redirect_url = import_string(logout_url_method)(request)
        logger.debug("OIDC logout for %s", email)
    else:
        logger.debug("Session logout for %s", email)

    logout(request)
    return HttpResponseRedirect(redirect_url)
