"""Simple views for the portal."""

from django.shortcuts import render


def home(request):
    """Landing page - coming soon."""
    return render(request, "coming_soon.html")
