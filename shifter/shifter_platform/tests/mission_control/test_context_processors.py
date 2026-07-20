"""Behavior tests for the mission_control ``active_range`` context processor.

Drives the real context processor against real ``RangeInstance`` rows — the
stored ``range_spec`` controls which instances the projection carries, and the
user's real group membership decides ``is_ctf_participant_only`` — instead of
patching ``get_active_range`` / ``is_ctf_participant_only`` / ``logger``. Runtime
private IPs come from a real linked engine ``Range``.

The page-tier split (#898) is also covered against real rows in
``TestActiveRangeContextTier``. Generic fault-injection / impossible-return-type
tests (mock ``get_active_range`` to raise or return a non-RangeContext) are
dropped per the boundary-mock policy; the real nav-tier fail-soft path is pinned
by ``test_nav_tier_fails_soft_on_service_error``.
"""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import RequestFactory

from shared.auth import CTF_PARTICIPANT_GROUP
from shared.enums import RequestType, ResourceStatus

pytestmark = pytest.mark.django_db

User = get_user_model()

TERMINAL_VIEW = "mission_control:terminal"


@pytest.fixture
def user(db):
    return User.objects.create_user(username="ctx@example.com", email="ctx@example.com")


@pytest.fixture
def ctf_user(db):
    """A CTF-participant-only user (so is_ctf_participant_only is True)."""
    u = User.objects.create_user(username="ctxctf@example.com", email="ctxctf@example.com")
    group, _ = Group.objects.get_or_create(name=CTF_PARTICIPANT_GROUP)
    u.groups.add(group)
    return u


def _request(user, view_name=TERMINAL_VIEW):
    request = RequestFactory().get("/")
    request.user = user
    request.resolver_match = SimpleNamespace(view_name=view_name) if view_name else None
    return request


def _instance(os_type, *, uuid=None, role=None, name=None):
    return {
        "uuid": uuid or str(uuid4()),
        "name": name or os_type,
        "role": role or ("attacker" if os_type == "kali" else "victim"),
        "os_type": os_type,
    }


def _seed_range(user, *, instances, status="ready", scenario_id="basic", range_id=None, engine_ips=None):
    """Seed a real CMS RangeInstance whose get_active_range projects ``instances``.

    When ``engine_ips`` ({uuid: ip}) and ``range_id`` are given, also create the
    linked engine Range so the projection overlays real runtime private IPs.
    """
    from cms.models import RangeInstance
    from cms.models import Request as CMSRequest

    request = CMSRequest.objects.create(request_id=uuid4(), request_type=RequestType.RANGE.value, user=user)
    range_instance = RangeInstance.objects.create(
        request=request,
        scenario_id=scenario_id,
        user_id=user.id,
        status=status,
        range_id=range_id,
        range_spec={"instances": instances},
    )
    if engine_ips and range_id is not None:
        from engine.models import Range as EngineRange

        EngineRange.objects.create(
            id=range_id,
            user=user,
            status="ready",
            provisioned_instances=[{"uuid": u, "private_ip": ip} for u, ip in engine_ips.items()],
        )
    return range_instance


class TestActiveRangeLookup:
    def test_returns_ready_active_range(self, user):
        from mission_control.context_processors import active_range
        from shared.schemas import RangeContext

        _seed_range(user, instances=[_instance("kali")])
        result = active_range(_request(user))

        assert result["has_active_range"] is True
        assert isinstance(result["active_range"], RangeContext)
        assert result["active_range"].status == ResourceStatus.READY

    def test_non_ready_range_is_not_active(self, user):
        from mission_control.context_processors import active_range

        _seed_range(user, instances=[_instance("kali")], status="provisioning")
        result = active_range(_request(user))

        assert result["has_active_range"] is False
        assert result["active_range"].status == ResourceStatus.PROVISIONING

    def test_returns_empty_when_no_active_range(self, user):
        from mission_control.context_processors import active_range

        result = active_range(_request(user))

        assert result["has_active_range"] is False
        assert result["active_range"] is None
        assert result["terminal_instances"] == []

    def test_returns_empty_for_unauthenticated_user(self):
        from django.contrib.auth.models import AnonymousUser

        from mission_control.context_processors import active_range

        request = RequestFactory().get("/")
        request.user = AnonymousUser()

        result = active_range(request)

        assert result["has_active_range"] is False
        assert result["active_range"] is None


class TestActiveRangeInstanceFiltering:
    def test_ctf_participant_only_sees_kali(self, ctf_user):
        from mission_control.context_processors import active_range

        _seed_range(
            ctf_user,
            instances=[_instance("kali"), _instance("ubuntu"), _instance("windows"), _instance("panos")],
        )
        result = active_range(_request(ctf_user))

        assert [i.os_type for i in result["active_range"].instances] == ["kali"]
        assert len(result["connection_urls"]) == 1

    def test_non_ctf_user_sees_all_instances(self, user):
        from mission_control.context_processors import active_range

        _seed_range(
            user,
            instances=[_instance("kali"), _instance("ubuntu"), _instance("windows"), _instance("panos")],
        )
        result = active_range(_request(user))

        assert len(result["active_range"].instances) == 4
        assert len(result["connection_urls"]) == 4

    def test_ctf_participant_without_kali_gets_empty(self, ctf_user):
        from mission_control.context_processors import active_range

        _seed_range(ctf_user, instances=[_instance("ubuntu"), _instance("windows")])
        result = active_range(_request(ctf_user))

        assert result["active_range"].instances == []
        assert result["connection_urls"] == []

    def test_ctf_participant_sees_all_kali(self, ctf_user):
        from mission_control.context_processors import active_range

        _seed_range(ctf_user, instances=[_instance("kali"), _instance("kali"), _instance("windows")])
        result = active_range(_request(ctf_user))

        assert [i.os_type for i in result["active_range"].instances] == ["kali", "kali"]
        assert len(result["connection_urls"]) == 2


class TestTerminalInstancesPayload:
    def test_payload_shape_with_runtime_ip(self, user):
        from mission_control.context_processors import active_range

        _seed_range(
            user,
            instances=[
                _instance("kali", uuid="att-1", role="attacker", name="AttackerKali"),
                _instance("windows", uuid="vic-1", role="victim", name="VictimWin"),
            ],
            range_id=4242,
            engine_ips={"att-1": "10.0.1.5"},
        )
        result = active_range(_request(user))

        assert result["terminal_instances"] == [
            {"uuid": "att-1", "role": "attacker", "osType": "kali", "name": "AttackerKali", "privateIp": "10.0.1.5"},
            {"uuid": "vic-1", "role": "victim", "osType": "windows", "name": "VictimWin", "privateIp": None},
        ]

    def test_payload_respects_ctf_filtering(self, ctf_user):
        from mission_control.context_processors import active_range

        _seed_range(
            ctf_user,
            instances=[
                _instance("kali", uuid="k", name="K"),
                _instance("windows", uuid="w", name="W"),
            ],
        )
        result = active_range(_request(ctf_user))

        assert [row["uuid"] for row in result["terminal_instances"]] == ["k"]

    def test_payload_empty_when_no_active_range(self, user):
        from mission_control.context_processors import active_range

        result = active_range(_request(user))

        assert result["terminal_instances"] == []


@pytest.mark.django_db
class TestActiveRangeContextTier:
    """Page-scoped context depth (#898): the full active-range payload is built
    only for the terminal render; every other authenticated page gets the cheap
    ``has_active_range`` indicator without FK joins, runtime IPs, or terminal JSON.

    Asserted through the processor's observable context output against real range
    rows — the per-tier query-cost reduction is pinned separately by the rendered
    page-render budgets and ``TestHasReadyActiveRange`` — so no internal service
    call is patched (ADR-019-R1 boundary-mock policy).
    """

    def _seed_ready_range(self, user):
        _seed_range(user, instances=[_instance("kali")])

    def test_non_terminal_page_indicates_range_without_full_payload(self, user):
        from mission_control.context_processors import active_range

        self._seed_ready_range(user)
        result = active_range(_request(user, "mission_control:dashboard"))

        # Indicator true, but the terminal-only payload is NOT built even though a
        # ready range exists — proof the nav tier skipped get_active_range.
        assert result["has_active_range"] is True
        assert result["active_range"] is None
        assert result["connection_urls"] == []
        assert result["scenario_name"] is None
        assert result["terminal_instances"] == []

    def test_non_terminal_page_false_when_no_range(self, user):
        from mission_control.context_processors import active_range

        result = active_range(_request(user, "mission_control:dashboard"))

        assert result["has_active_range"] is False
        assert result["active_range"] is None

    def test_missing_resolver_match_uses_nav_tier(self, user):
        """A render with no resolved view (e.g. error pages) defaults to nav tier."""
        from mission_control.context_processors import active_range

        self._seed_ready_range(user)
        result = active_range(_request(user, None))

        assert result["has_active_range"] is True
        assert result["active_range"] is None

    def test_nav_tier_fails_soft_on_service_error(self):
        """An unsaved user makes the CMS indicator raise; the nav tier must swallow
        it into the safe empty context rather than 500 the page."""
        from mission_control.context_processors import active_range

        unsaved = User(username="unsaved@example.com")  # id is None -> ValueError in service
        result = active_range(_request(unsaved, "mission_control:dashboard"))

        assert result["has_active_range"] is False
        assert result["active_range"] is None

    def test_terminal_page_builds_full_payload(self, user):
        from mission_control.context_processors import active_range
        from shared.schemas import RangeContext

        self._seed_ready_range(user)
        result = active_range(_request(user, TERMINAL_VIEW))

        # The terminal tier builds the real RangeContext projection.
        assert isinstance(result["active_range"], RangeContext)
        assert result["has_active_range"] is True
