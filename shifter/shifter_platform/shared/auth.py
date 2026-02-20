"""Access control utilities for Shifter views."""

from django.contrib.auth.decorators import user_passes_test

THREAT_RESEARCH_GROUP = "Threat Research"


def _is_staff_or_threat_researcher(user):
    """Return True if the user is active and is staff or in the Threat Research group."""
    if not user.is_active:
        return False
    if user.is_staff:
        return True
    return user.groups.filter(name=THREAT_RESEARCH_GROUP).exists()


# Drop-in replacement for @staff_member_required that also grants access to
# members of the Threat Research group. Uses the same redirect target as the
# Django staff_member_required decorator.
threat_research_required = user_passes_test(
    _is_staff_or_threat_researcher,
    login_url="admin:index",
)
