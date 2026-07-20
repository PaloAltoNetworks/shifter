"""Shared fixtures for risk register Cognito group authorization tests."""

from __future__ import annotations

import pytest

ALLOWED_GROUPS = ["security"]


@pytest.fixture(autouse=True)
def risk_register_allowed_groups(settings):
    settings.RISK_REGISTER_ALLOWED_COGNITO_GROUPS = ALLOWED_GROUPS


def grant_risk_register_access(user, groups=None):
    from management.services import get_user_profile

    profile = get_user_profile(user)
    profile.cognito_groups = list(groups or ALLOWED_GROUPS)
    profile.save(update_fields=["cognito_groups"])
    return profile
