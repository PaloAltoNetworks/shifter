"""Tests covering CMS service range-lifecycle branches not exercised elsewhere.

Targets `_range_destroy.py`, `_range_pause.py`, `_range_resume.py`, and the
missing input-validation paths in `_range_create.py`.
"""

from __future__ import annotations

from unittest.mock import MagicMock, Mock, patch
from uuid import uuid4

import pytest

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_user():
    user = MagicMock()
    user.id = 42
    user.pk = 42
    user.email = "u@example.com"
    return user


def _mock_request():
    req = MagicMock()
    req.request_id = uuid4()
    return req


def _mock_range(user_id=42, *, range_id=42, request=None, scenario_id="basic"):
    inst = MagicMock()
    inst.range_id = range_id
    inst.id = range_id
    inst.user_id = user_id
    inst.scenario_id = scenario_id
    inst.request = request if request is not None else _mock_request()
    inst.agent = None
    inst.save = MagicMock()
    return inst


# ---------------------------------------------------------------------------
# destroy_range — branches not exercised by existing tests
# ---------------------------------------------------------------------------


class TestDestroyRangeValidation:
    def test_raises_typeerror_for_none_range_id(self, mock_user):
        from cms.services import destroy_range

        with pytest.raises(TypeError, match="range_id cannot be None"):
            destroy_range(mock_user, None)

    def test_raises_typeerror_for_wrong_type(self, mock_user):
        from cms.services import destroy_range

        with pytest.raises(TypeError, match="range_id must be an int"):
            destroy_range(mock_user, "not-int")

    def test_raises_valueerror_for_negative(self, mock_user):
        from cms.services import destroy_range

        with pytest.raises(ValueError, match="non-negative"):
            destroy_range(mock_user, -3)

    def test_raises_cms_error_when_no_request(self, mock_user):
        from cms.exceptions import CMSError
        from cms.services import destroy_range

        inst = _mock_range()
        inst.request = None
        with (
            patch("cms.services.RangeInstance.objects.get", return_value=inst),
            patch("cms.services.engine_destroy_range_by_request"),
            pytest.raises(CMSError, match="no associated request"),
        ):
            destroy_range(mock_user, 42)


# ---------------------------------------------------------------------------
# cancel_range — validation + error paths
# ---------------------------------------------------------------------------


class TestCancelRangeValidation:
    def test_raises_typeerror_for_none_range_id(self, mock_user):
        from cms.services import cancel_range

        with pytest.raises(TypeError, match="range_id cannot be None"):
            cancel_range(mock_user, None)

    def test_raises_typeerror_for_wrong_type(self, mock_user):
        from cms.services import cancel_range

        with pytest.raises(TypeError, match="range_id must be an int"):
            cancel_range(mock_user, "not-int")

    def test_raises_valueerror_for_negative(self, mock_user):
        from cms.services import cancel_range

        with pytest.raises(ValueError, match="non-negative"):
            cancel_range(mock_user, -1)

    def test_raises_cms_error_when_get_range_returns_none(self, mock_user):
        from cms import services
        from cms.exceptions import CMSError
        from cms.services import cancel_range

        with patch.object(services, "get_range", return_value=None), pytest.raises(CMSError, match="not found"):
            cancel_range(mock_user, 42)

    def test_raises_cms_error_when_no_request(self, mock_user):
        from cms import services
        from cms.exceptions import CMSError
        from cms.services import cancel_range

        inst = _mock_range()
        inst.request = None
        with (
            patch.object(services, "get_range", return_value=inst),
            patch("cms.services.engine_cancel_range_by_request"),
            pytest.raises(CMSError, match="no associated request"),
        ):
            cancel_range(mock_user, 42)


# ---------------------------------------------------------------------------
# destroy_range_by_request_id — full happy + error paths
# ---------------------------------------------------------------------------


class TestDestroyRangeByRequestId:
    def test_raises_typeerror_for_none_user(self):
        from cms.services import destroy_range_by_request_id

        with pytest.raises(TypeError):
            destroy_range_by_request_id(None, str(uuid4()))

    def test_raises_typeerror_for_invalid_user(self):
        from cms.services import destroy_range_by_request_id

        with pytest.raises(TypeError, match="User instance"):
            destroy_range_by_request_id("not-user", str(uuid4()))

    def test_raises_cms_error_for_empty_request_id(self, mock_user):
        from cms.exceptions import CMSError
        from cms.services import destroy_range_by_request_id

        with pytest.raises(CMSError, match="request_id is required"):
            destroy_range_by_request_id(mock_user, "")

    def test_raises_cms_error_when_not_found(self, mock_user):
        from cms.exceptions import CMSError
        from cms.services import destroy_range_by_request_id

        with patch("cms.services.RangeInstance.objects.filter") as mf:
            mf.return_value.first.return_value = None
            with pytest.raises(CMSError, match="not found"):
                destroy_range_by_request_id(mock_user, str(uuid4()))

    def test_raises_when_no_request(self, mock_user):
        from cms.exceptions import CMSError
        from cms.services import destroy_range_by_request_id

        inst = _mock_range()
        inst.request = None
        with patch("cms.services.RangeInstance.objects.filter") as mf:
            mf.return_value.first.return_value = inst
            with pytest.raises(CMSError, match="no associated request"):
                destroy_range_by_request_id(mock_user, str(uuid4()))

    def test_happy_path_calls_engine_and_audits(self, mock_user):
        from cms.services import destroy_range_by_request_id

        inst = _mock_range()
        rid = str(uuid4())
        with (
            patch("cms.services.RangeInstance.objects.filter") as mf,
            patch("cms.services.engine_destroy_range_by_request") as eng,
            patch("cms.services.audit_log") as audit,
        ):
            mf.return_value.first.return_value = inst
            destroy_range_by_request_id(mock_user, rid)

        eng.assert_called_once_with(inst.request.request_id)
        audit.assert_called_once()
        inst.save.assert_called()


# ---------------------------------------------------------------------------
# cancel_range_by_request_id
# ---------------------------------------------------------------------------


class TestCancelRangeByRequestId:
    def test_raises_typeerror_for_none_user(self):
        from cms.services import cancel_range_by_request_id

        with pytest.raises(TypeError):
            cancel_range_by_request_id(None, str(uuid4()))

    def test_raises_typeerror_for_invalid_user(self):
        from cms.services import cancel_range_by_request_id

        with pytest.raises(TypeError, match="User instance"):
            cancel_range_by_request_id("not-user", str(uuid4()))

    def test_raises_cms_error_for_empty_request_id(self, mock_user):
        from cms.exceptions import CMSError
        from cms.services import cancel_range_by_request_id

        with pytest.raises(CMSError, match="request_id is required"):
            cancel_range_by_request_id(mock_user, "")

    def test_raises_cms_error_when_not_found(self, mock_user):
        from cms.exceptions import CMSError
        from cms.services import cancel_range_by_request_id

        with patch("cms.services.RangeInstance.objects.filter") as mf:
            mf.return_value.first.return_value = None
            with pytest.raises(CMSError, match="not found"):
                cancel_range_by_request_id(mock_user, str(uuid4()))

    def test_raises_when_no_request(self, mock_user):
        from cms.exceptions import CMSError
        from cms.services import cancel_range_by_request_id

        inst = _mock_range()
        inst.request = None
        with patch("cms.services.RangeInstance.objects.filter") as mf:
            mf.return_value.first.return_value = inst
            with pytest.raises(CMSError, match="no associated request"):
                cancel_range_by_request_id(mock_user, str(uuid4()))

    def test_happy_path_calls_engine_and_audits(self, mock_user):
        from cms.services import cancel_range_by_request_id

        inst = _mock_range()
        with (
            patch("cms.services.RangeInstance.objects.filter") as mf,
            patch("cms.services.engine_cancel_range_by_request") as eng,
            patch("cms.services.audit_log") as audit,
        ):
            mf.return_value.first.return_value = inst
            cancel_range_by_request_id(mock_user, str(uuid4()))

        eng.assert_called_once_with(inst.request.request_id)
        audit.assert_called_once()


# ---------------------------------------------------------------------------
# pause_range / resume_range — missing branches
# ---------------------------------------------------------------------------


class TestPauseRangeValidation:
    def test_raises_typeerror_for_none_range_id(self, mock_user):
        from cms.services import pause_range

        with pytest.raises(TypeError, match="range_id cannot be None"):
            pause_range(mock_user, None)

    def test_raises_typeerror_for_wrong_type(self, mock_user):
        from cms.services import pause_range

        with pytest.raises(TypeError, match="range_id must be an int"):
            pause_range(mock_user, "x")

    def test_raises_valueerror_for_negative(self, mock_user):
        from cms.services import pause_range

        with pytest.raises(ValueError, match="non-negative"):
            pause_range(mock_user, -2)

    def test_raises_cms_error_when_no_request(self, mock_user):
        from cms.exceptions import CMSError
        from cms.services import pause_range

        inst = _mock_range()
        inst.request = None
        with (
            patch("cms.services.RangeInstance.objects.get", return_value=inst),
            pytest.raises(CMSError, match="no associated request"),
        ):
            pause_range(mock_user, 42)


class TestResumeRangeValidation:
    def test_raises_typeerror_for_none_range_id(self, mock_user):
        from cms.services import resume_range

        with pytest.raises(TypeError, match="range_id cannot be None"):
            resume_range(mock_user, None)

    def test_raises_typeerror_for_wrong_type(self, mock_user):
        from cms.services import resume_range

        with pytest.raises(TypeError, match="range_id must be an int"):
            resume_range(mock_user, "x")

    def test_raises_valueerror_for_negative(self, mock_user):
        from cms.services import resume_range

        with pytest.raises(ValueError, match="non-negative"):
            resume_range(mock_user, -2)

    def test_raises_cms_error_when_no_request(self, mock_user):
        from cms.exceptions import CMSError
        from cms.services import resume_range

        inst = _mock_range()
        inst.request = None
        with (
            patch("cms.services.RangeInstance.objects.get", return_value=inst),
            pytest.raises(CMSError, match="no associated request"),
        ):
            resume_range(mock_user, 42)


class TestPauseResumeByRequestIdValidation:
    def test_pause_raises_typeerror_for_none_user(self):
        from cms.services import pause_range_by_request_id

        with pytest.raises(TypeError):
            pause_range_by_request_id(None, str(uuid4()))

    def test_pause_raises_typeerror_for_invalid_user(self):
        from cms.services import pause_range_by_request_id

        with pytest.raises(TypeError, match="User instance"):
            pause_range_by_request_id("x", str(uuid4()))

    def test_pause_raises_cms_error_for_empty_request_id(self, mock_user):
        from cms.exceptions import CMSError
        from cms.services import pause_range_by_request_id

        with pytest.raises(CMSError, match="request_id is required"):
            pause_range_by_request_id(mock_user, "")

    def test_pause_raises_cms_error_when_no_request(self, mock_user):
        from cms.exceptions import CMSError
        from cms.services import pause_range_by_request_id

        inst = _mock_range()
        inst.request = None
        with patch("cms.services.RangeInstance.objects.filter") as mf:
            mf.return_value.first.return_value = inst
            with pytest.raises(CMSError, match="no associated request"):
                pause_range_by_request_id(mock_user, str(uuid4()))

    def test_resume_raises_typeerror_for_none_user(self):
        from cms.services import resume_range_by_request_id

        with pytest.raises(TypeError):
            resume_range_by_request_id(None, str(uuid4()))

    def test_resume_raises_typeerror_for_invalid_user(self):
        from cms.services import resume_range_by_request_id

        with pytest.raises(TypeError, match="User instance"):
            resume_range_by_request_id("x", str(uuid4()))

    def test_resume_raises_cms_error_for_empty_request_id(self, mock_user):
        from cms.exceptions import CMSError
        from cms.services import resume_range_by_request_id

        with pytest.raises(CMSError, match="request_id is required"):
            resume_range_by_request_id(mock_user, "")

    def test_resume_raises_cms_error_when_no_request(self, mock_user):
        from cms.exceptions import CMSError
        from cms.services import resume_range_by_request_id

        inst = _mock_range()
        inst.request = None
        with patch("cms.services.RangeInstance.objects.filter") as mf:
            mf.return_value.first.return_value = inst
            with pytest.raises(CMSError, match="no associated request"):
                resume_range_by_request_id(mock_user, str(uuid4()))


# ---------------------------------------------------------------------------
# create_range — input-validation branches
# ---------------------------------------------------------------------------


class TestCreateRangeInputValidation:
    def test_raises_typeerror_for_none_user(self):
        from cms.services import create_range

        with pytest.raises(TypeError):
            create_range(None, "basic", {"windows": 1})

    def test_raises_typeerror_for_invalid_user(self):
        from cms.services import create_range

        with pytest.raises(TypeError, match="User instance"):
            create_range("not-user", "basic", {"windows": 1})

    def test_raises_valueerror_for_unsaved_user(self):
        from cms.services import create_range

        unsaved = MagicMock()
        unsaved.id = None
        with pytest.raises(ValueError):
            create_range(unsaved, "basic", {"windows": 1})

    def test_raises_valueerror_for_none_scenario(self, mock_user):
        from cms.services import create_range

        with pytest.raises(ValueError, match="scenario cannot be None"):
            create_range(mock_user, None, {"windows": 1})

    def test_raises_valueerror_for_empty_scenario(self, mock_user):
        from cms.services import create_range

        with pytest.raises(ValueError, match="non-empty string"):
            create_range(mock_user, "", {"windows": 1})

    def test_raises_valueerror_for_nonstring_scenario(self, mock_user):
        from cms.services import create_range

        with pytest.raises(ValueError, match="non-empty string"):
            create_range(mock_user, 7, {"windows": 1})

    def test_raises_typeerror_for_none_agents(self, mock_user):
        from cms.services import create_range

        with pytest.raises(TypeError, match="agents_by_os cannot be None"):
            create_range(mock_user, "basic", None)

    def test_raises_typeerror_for_nondict_agents(self, mock_user):
        from cms.services import create_range

        with pytest.raises(TypeError, match="agents_by_os must be a dict"):
            create_range(mock_user, "basic", ["windows", 1])


class TestCreateRangeScenarioRequirements:
    """Cover the requires_windows / requires_linux / has_from_agent branches."""

    @pytest.fixture
    def template_factory(self, mock_user):
        from cms.exceptions import CMSError
        from cms.services import create_range

        def run(requirements, agents):
            template = Mock()
            template.get_agent_requirements.return_value = requirements
            template.ngfw = False
            with (
                patch("cms.services.get_active_range", return_value=None),
                patch(
                    "cms.scenarios.registry.load_scenario_template",
                    return_value=template,
                ),
                pytest.raises(CMSError),
            ):
                create_range(mock_user, "basic", agents)

        return run

    def test_requires_windows(self, template_factory):
        template_factory(
            {"requires_windows": True, "requires_linux": False, "has_from_agent": False},
            {"linux": 1},
        )

    def test_requires_linux(self, template_factory):
        template_factory(
            {"requires_windows": False, "requires_linux": True, "has_from_agent": False},
            {"windows": 1},
        )

    def test_requires_at_least_one_agent(self, template_factory):
        template_factory(
            {"requires_windows": False, "requires_linux": False, "has_from_agent": True},
            {},
        )
