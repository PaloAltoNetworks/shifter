"""Simple views for the platform."""

import logging

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse

from management.services import get_user_profile

logger = logging.getLogger(__name__)


def home(request):
    """Landing page - coming soon."""
    return render(request, "coming_soon.html")


@login_required
def dashboard_router(request):
    """Route authenticated users to the correct dashboard based on user type.

    - standard users -> Mission Control dashboard
    - ctf_organizer -> CTF Admin dashboard
    - ctf_participant -> CTF Participant dashboard
    """
    profile = get_user_profile(request.user)

    if profile.is_ctf_organizer:
        logger.debug("Routing organizer %s to CTF admin dashboard", request.user.email)
        return HttpResponseRedirect(reverse("ctf:admin_dashboard"))
    elif profile.is_ctf_participant:
        logger.debug("Routing participant %s to CTF participant dashboard", request.user.email)
        return HttpResponseRedirect(reverse("ctf:participant_dashboard"))
    else:
        logger.debug("Routing standard user %s to Mission Control", request.user.email)
        return HttpResponseRedirect(reverse("mission_control:dashboard"))
