"""Tests for shared.auth access control utilities."""

from unittest.mock import MagicMock

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory

from shared.auth import (
    CTF_ORGANIZER_GROUP,
    CTF_PARTICIPANT_GROUP,
    THREAT_RESEARCH_GROUP,
    block_ctf_participant_only,
    can_edit_cms_authoring,
    threat_research_required,
    validate_cms_authoring_user,
)
from shared.constants import USER_CANNOT_BE_NONE, USER_MUST_BE_SAVED


def _make_user(is_staff=False, is_active=True, groups=None):
    """Create a mock user with the given properties.

    The group predicates now resolve membership through
    ``shared.auth.get_user_group_names``, which reads
    ``user.groups.values_list("name", flat=True)`` once per request, so the mock
    exposes the group-name list rather than ``filter(...).exists()``.
    """
    user = MagicMock()
    user.is_staff = is_staff
    user.is_active = is_active
    user.is_authenticated = True
    user.is_anonymous = False
    user.pk = 1
    user.groups.values_list.return_value = list(groups or [])
    return user


class TestValidateCmsAuthoringUser:
    """Unit tests for validate_cms_authoring_user — the shared service-layer
    gate that combines structural user checks with the CMS authoring policy.
    """

    def test_none_user_raises_type_error(self):
        with pytest.raises(TypeError, match=USER_CANNOT_BE_NONE):
            validate_cms_authoring_user(None, "svc")

    def test_non_user_object_raises_type_error(self):
        with pytest.raises(TypeError, match="must be a User instance"):
            validate_cms_authoring_user("not-a-user", "svc")

    def test_unsaved_user_raises_value_error(self):
        import re

        unsaved = MagicMock()
        unsaved.id = None
        with pytest.raises(ValueError, match=re.escape(USER_MUST_BE_SAVED)):
            validate_cms_authoring_user(unsaved, "svc")

    def test_unrelated_authenticated_user_denied(self):
        user = _make_user(is_staff=False)
        user.id = 7
        with pytest.raises(PermissionDenied, match="Active staff or Threat Research"):
            validate_cms_authoring_user(user, "svc")

    def test_inactive_threat_research_user_denied(self):
        user = _make_user(is_staff=False, is_active=False, groups=[THREAT_RESEARCH_GROUP])
        user.id = 7
        with pytest.raises(PermissionDenied, match="Active staff or Threat Research"):
            validate_cms_authoring_user(user, "svc")

    def test_active_staff_user_passes(self):
        user = _make_user(is_staff=True)
        user.id = 7
        assert validate_cms_authoring_user(user, "svc") is None

    def test_active_threat_research_user_passes(self):
        user = _make_user(is_staff=False, groups=[THREAT_RESEARCH_GROUP])
        user.id = 7
        assert validate_cms_authoring_user(user, "svc") is None


class TestCanEditCmsAuthoring:
    """Unit tests for can_edit_cms_authoring helper."""

    def test_active_staff_returns_true(self):
        user = _make_user(is_staff=True)
        assert can_edit_cms_authoring(user) is True

    def test_active_threat_research_member_returns_true(self):
        user = _make_user(is_staff=False, groups=[THREAT_RESEARCH_GROUP])
        assert can_edit_cms_authoring(user) is True

    def test_inactive_staff_returns_false(self):
        user = _make_user(is_staff=True, is_active=False)
        assert can_edit_cms_authoring(user) is False

    def test_inactive_threat_research_member_returns_false(self):
        user = _make_user(is_staff=False, is_active=False, groups=[THREAT_RESEARCH_GROUP])
        assert can_edit_cms_authoring(user) is False

    def test_regular_user_returns_false(self):
        user = _make_user(is_staff=False)
        assert can_edit_cms_authoring(user) is False

    def test_anonymous_user_returns_false(self):
        assert can_edit_cms_authoring(AnonymousUser()) is False


class TestThreatResearchRequiredDecorator:
    """Unit tests for the threat_research_required decorator."""

    def setup_method(self):
        self.factory = RequestFactory()

        from django.http import HttpResponse

        @threat_research_required
        def dummy_view(request):
            return HttpResponse("ok")

        self.view = dummy_view

    def _make_request(self, user=None):
        request = self.factory.get("/test/")
        if user is None:
            request.user = AnonymousUser()
        else:
            request.user = user
        from django.contrib.messages.storage.fallback import FallbackStorage

        request.session = {}
        request._messages = FallbackStorage(request)
        return request

    def test_unauthenticated_redirects_to_login(self):
        from django.conf import settings
        from django.shortcuts import resolve_url

        request = self._make_request()
        resp = self.view(request)
        assert resp.status_code == 302
        # Positively assert the destination is the configured login URL — not
        # merely "not admin" — so a refactor that redirected the unauthenticated
        # branch anywhere else fails here. resolve_url mirrors what redirect()
        # does to LOGIN_URL (a path when DEBUG, a URL name otherwise).
        assert resp.url == resolve_url(settings.LOGIN_URL)

    def test_unauthorized_redirects_to_dashboard(self):
        user = _make_user(is_staff=False)
        request = self._make_request(user=user)
        resp = self.view(request)
        assert resp.status_code == 302
        # The redirect URL should be the mission_control:dashboard URL
        assert "mission-control" in resp.url

    def test_unauthorized_sets_error_message(self):
        user = _make_user(is_staff=False)
        request = self._make_request(user=user)
        self.view(request)
        msgs = [str(m) for m in request._messages]
        assert any("permission" in m.lower() for m in msgs)

    def test_staff_passes_through(self):
        user = _make_user(is_staff=True)
        request = self._make_request(user=user)
        resp = self.view(request)
        assert resp.status_code == 200
        assert resp.content == b"ok"

    def test_threat_research_member_passes_through(self):
        user = _make_user(is_staff=False, groups=[THREAT_RESEARCH_GROUP])
        request = self._make_request(user=user)
        resp = self.view(request)
        assert resp.status_code == 200
        assert resp.content == b"ok"

    def test_unauthorized_log_escapes_crlf_in_path(self, caplog):
        """A user-controlled request.path with CR/LF is escaped in the denial
        log so it cannot forge log entries (CodeQL py/log-injection)."""
        import logging

        user = _make_user(is_staff=False)
        request = self._make_request(user=user)
        request.path = "/threat/\r\nINJECTED forged-entry"
        with caplog.at_level(logging.WARNING):
            self.view(request)

        denials = [r for r in caplog.records if "denied access" in r.getMessage()]
        assert denials, "expected a denial warning log record"
        msg = denials[0].getMessage()
        assert "\r" not in msg and "\n" not in msg  # raw control chars removed
        assert "\\r\\n" in msg  # escaped form present
        assert "INJECTED" in msg  # value preserved, only escaped


class TestBlockCtfParticipantOnlyDecorator:
    """Unit tests for the block_ctf_participant_only lifecycle guard (#944).

    The guard rejects CTF participant-only accounts from a range lifecycle verb
    they are not explicitly allowed to invoke, server-side at the HTTP boundary.
    """

    def setup_method(self):
        self.factory = RequestFactory()

        from django.http import JsonResponse

        @block_ctf_participant_only("destroy")
        def dummy_view(request):
            return JsonResponse({"success": True})

        self.view = dummy_view

    def _make_post(self, user):
        request = self.factory.post("/api/range/destroy/")
        request.user = user
        return request

    @staticmethod
    def _user(*, is_staff=False, is_superuser=False, is_active=True, groups=None):
        user = MagicMock()
        user.is_staff = is_staff
        user.is_superuser = is_superuser
        user.is_active = is_active
        user.is_authenticated = True
        user.pk = 42
        user.groups.values_list.return_value = list(groups or [])
        return user

    def test_participant_only_user_is_forbidden(self):
        user = self._user(groups=[CTF_PARTICIPANT_GROUP])
        resp = self.view(self._make_post(user))
        assert resp.status_code == 403
        import json

        assert json.loads(resp.content) == {"error": "Forbidden"}

    def test_organizer_only_user_is_forbidden(self):
        # Organizers are also "participant-only" per is_ctf_participant_only:
        # they hold a CTF role but are not staff/superuser/Threat Research, so a
        # direct lifecycle call from an organizer account is blocked too. The
        # organizer's on-behalf-of provisioning runs through ctf.services -> CMS,
        # not these MC views, so it is unaffected.
        user = self._user(groups=[CTF_ORGANIZER_GROUP])
        resp = self.view(self._make_post(user))
        assert resp.status_code == 403

    def test_staff_user_passes_through(self):
        user = self._user(is_staff=True, groups=[CTF_PARTICIPANT_GROUP])
        resp = self.view(self._make_post(user))
        assert resp.status_code == 200

    def test_threat_research_member_passes_through(self):
        user = self._user(groups=[CTF_PARTICIPANT_GROUP, THREAT_RESEARCH_GROUP])
        resp = self.view(self._make_post(user))
        assert resp.status_code == 200

    def test_plain_non_ctf_user_passes_through(self):
        user = self._user(groups=[])
        resp = self.view(self._make_post(user))
        assert resp.status_code == 200

    def test_allowlisted_verb_permits_participant(self, monkeypatch):
        # Seam coverage: when a verb is added to the allowlist, a participant-only
        # account is permitted that verb even though the shipped allowlist is empty.
        monkeypatch.setattr("shared.auth.PARTICIPANT_ALLOWED_LIFECYCLE_VERBS", frozenset({"destroy"}))
        user = self._user(groups=[CTF_PARTICIPANT_GROUP])
        resp = self.view(self._make_post(user))
        assert resp.status_code == 200

    def test_shipped_allowlist_is_empty(self):
        from shared.auth import PARTICIPANT_ALLOWED_LIFECYCLE_VERBS

        assert not PARTICIPANT_ALLOWED_LIFECYCLE_VERBS
        assert isinstance(PARTICIPANT_ALLOWED_LIFECYCLE_VERBS, frozenset)


@pytest.mark.django_db
class TestGetUserGroupNames:
    """Request-scoped group-name memoization that collapses the portal context
    processors' repeated ``user.groups`` lookups to one query per render (#898).
    """

    def _user_with_groups(self, *names):
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import Group

        user = get_user_model().objects.create_user(username="ggn@example.com", email="ggn@example.com")
        for name in names:
            group, _ = Group.objects.get_or_create(name=name)
            user.groups.add(group)
        return user

    def test_returns_group_names_as_frozenset(self):
        from shared.auth import CTF_PARTICIPANT_GROUP, get_user_group_names

        user = self._user_with_groups(CTF_PARTICIPANT_GROUP, THREAT_RESEARCH_GROUP)
        names = get_user_group_names(user)

        assert isinstance(names, frozenset)
        assert names == frozenset({CTF_PARTICIPANT_GROUP, THREAT_RESEARCH_GROUP})

    def test_empty_when_user_has_no_groups(self):
        from shared.auth import get_user_group_names

        user = self._user_with_groups()
        assert get_user_group_names(user) == frozenset()

    def test_memoizes_on_user_instance(self):
        """Repeated calls on the same user instance issue exactly one DB query."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        from shared.auth import CTF_PARTICIPANT_GROUP, get_user_group_names

        user = self._user_with_groups(CTF_PARTICIPANT_GROUP)
        with CaptureQueriesContext(connection) as ctx:
            get_user_group_names(user)
            get_user_group_names(user)
            get_user_group_names(user)

        assert len(ctx.captured_queries) == 1

    def test_predicates_share_one_query_per_user(self):
        """The four shared.auth group predicates resolve from a single cached
        lookup when called against the same request-scoped user instance."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        from shared.auth import (
            CTF_PARTICIPANT_GROUP,
            can_edit_cms_authoring,
            is_ctf_organizer,
            is_ctf_participant,
            is_ctf_participant_only,
        )

        user = self._user_with_groups(CTF_PARTICIPANT_GROUP)
        with CaptureQueriesContext(connection) as ctx:
            is_ctf_organizer(user)
            is_ctf_participant(user)
            is_ctf_participant_only(user)
            can_edit_cms_authoring(user)

        assert len(ctx.captured_queries) == 1
