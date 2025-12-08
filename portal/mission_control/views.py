"""Mission Control views."""

from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def dashboard(request):
    """Main dashboard - launch and manage ranges."""
    context = {
        "page_title": "Dashboard",
        "active_nav": "dashboard",
    }
    return render(request, "mission_control/dashboard.html", context)


@login_required
def agents(request):
    """Agent management - upload and manage XDR/XSIAM agents."""
    context = {
        "page_title": "Agents",
        "active_nav": "agents",
    }
    return render(request, "mission_control/agents.html", context)


@login_required
def history(request):
    """Range history - view past sessions."""
    context = {
        "page_title": "History",
        "active_nav": "history",
    }
    return render(request, "mission_control/history.html", context)


@login_required
def settings(request):
    """Account settings."""
    context = {
        "page_title": "Settings",
        "active_nav": "settings",
    }
    return render(request, "mission_control/settings.html", context)


@login_required
def help_page(request):
    """Help and documentation."""
    context = {
        "page_title": "Help",
        "active_nav": "help",
    }
    return render(request, "mission_control/help.html", context)
