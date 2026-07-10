"""Unit tests for IsOwnerOrAdmin ownership helpers (issue #779 burndown)."""

from types import SimpleNamespace

import pytest

from risk_register.api.permissions import IsOwnerOrAdmin

pytestmark = pytest.mark.django_db


def _user(*, uid="u1", authenticated=True, staff=False, superuser=False):
    return SimpleNamespace(uid=uid, is_authenticated=authenticated, is_staff=staff, is_superuser=superuser)


def _request(user=None, auth=None):
    return SimpleNamespace(user=user, auth=auth)


class TestIsAdmin:
    def test_staff_is_admin(self):
        assert IsOwnerOrAdmin._is_admin(_request(_user(staff=True))) is True

    def test_superuser_is_admin(self):
        assert IsOwnerOrAdmin._is_admin(_request(_user(superuser=True))) is True

    def test_plain_user_is_not_admin(self):
        assert IsOwnerOrAdmin._is_admin(_request(_user())) is False

    def test_unauthenticated_is_not_admin(self):
        assert IsOwnerOrAdmin._is_admin(_request(_user(authenticated=False, staff=True))) is False


class TestOwnsViaUser:
    def test_author_user_match(self):
        user = _user()
        assert IsOwnerOrAdmin._owns_via_user(_request(user), SimpleNamespace(author_user=user)) is True

    def test_created_by_match(self):
        user = _user()
        assert IsOwnerOrAdmin._owns_via_user(_request(user), SimpleNamespace(created_by=user)) is True

    def test_unauthenticated(self):
        assert IsOwnerOrAdmin._owns_via_user(_request(_user(authenticated=False)), SimpleNamespace()) is False

    def test_no_ownership(self):
        user = _user(uid="me")
        assert IsOwnerOrAdmin._owns_via_user(_request(user), SimpleNamespace(author_user=_user(uid="other"))) is False
