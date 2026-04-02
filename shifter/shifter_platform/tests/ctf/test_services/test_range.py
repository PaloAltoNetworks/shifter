"""Tests for CTF Range service.

Unit tests — mock all ORM access. We test our service logic
(branching, error wrapping, return values), not SQLite.
"""

from __future__ import annotations

from unittest.mock import Mock, patch
from uuid import uuid4

import pytest

from ctf.bridges import RangeProvisionResult
from ctf.exceptions import CTFNotFoundError, CTFRangeError
from ctf.models import CTFEvent, CTFParticipant
from ctf.services import range as range_service

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_participant():
    """Mock CTFParticipant with sensible defaults."""
    p = Mock(spec=CTFParticipant)
    p.pk = uuid4()
    p.range_instance_id = None
    p.range_status = ""
    p.user = Mock(email="participant@test.com")
    p.event = Mock(scenario_id="basic", range_config=None)
    return p


@pytest.fixture
def mock_participant_with_range(mock_participant):
    """Mock participant that already has a range assigned."""
    mock_participant.range_instance_id = 42
    mock_participant.range_status = "ready"
    return mock_participant


@pytest.fixture
def _patch_participant_get(mock_participant):
    """Patch CTFParticipant.objects so .get() and .select_related().get() return mock_participant."""
    with patch.object(CTFParticipant, "objects") as mock_objects:
        mock_objects.get.return_value = mock_participant
        mock_objects.select_related.return_value.get.return_value = mock_participant
        mock_objects.DoesNotExist = CTFParticipant.DoesNotExist
        yield mock_objects


@pytest.fixture
def _patch_participant_not_found():
    """Patch CTFParticipant.objects so .get() raises DoesNotExist."""
    with patch.object(CTFParticipant, "objects") as mock_objects:
        mock_objects.get.side_effect = CTFParticipant.DoesNotExist
        mock_objects.select_related.return_value.get.side_effect = CTFParticipant.DoesNotExist
        mock_objects.DoesNotExist = CTFParticipant.DoesNotExist
        yield mock_objects


class TestProvisionParticipantRange:
    """Tests for provision_participant_range."""

    def test_not_found(self, _patch_participant_not_found):
        """Raises CTFNotFoundError for nonexistent participant."""
        with pytest.raises(CTFNotFoundError):
            range_service.provision_participant_range(uuid4())

    @pytest.mark.usefixtures("_patch_participant_get")
    def test_already_assigned(self, mock_participant):
        """Raises CTFRangeError if participant already has a range."""
        mock_participant.range_instance_id = 42

        with pytest.raises(CTFRangeError, match="already has a range"):
            range_service.provision_participant_range(mock_participant.pk)

    @pytest.mark.usefixtures("_patch_participant_get")
    def test_provision_success(self, mock_participant):
        """Successful provisioning sets range_instance_id and status."""
        request_id = uuid4()
        mock_result = RangeProvisionResult(request_id=request_id)

        with (
            patch("ctf.bridges.cms_create_range", return_value=mock_result) as mock_create,
            patch("ctf.bridges.cms_find_range_instance_id", return_value=99),
        ):
            result = range_service.provision_participant_range(mock_participant.pk)

        assert result["status"] == "provisioning"
        mock_participant.save.assert_called_once()
        assert mock_participant.range_status == "provisioning"
        mock_create.assert_called_once()
        assert mock_create.call_args.kwargs["user"] == mock_participant.user

    @pytest.mark.usefixtures("_patch_participant_get")
    def test_provision_requires_registered_user(self, mock_participant):
        """Raises CTFRangeError if participant has no linked user."""
        mock_participant.user = None

        with pytest.raises(CTFRangeError, match="must be registered"):
            range_service.provision_participant_range(mock_participant.pk)

    @pytest.mark.usefixtures("_patch_participant_get")
    def test_provision_cms_failure(self, mock_participant):
        """CMS errors are wrapped in CTFRangeError."""
        with (
            patch("ctf.bridges.cms_create_range", side_effect=RuntimeError("CMS down")),
            pytest.raises(CTFRangeError, match="Range provisioning failed"),
        ):
            range_service.provision_participant_range(mock_participant.pk)


class TestProvisionEventRanges:
    """Tests for provision_event_ranges."""

    def test_not_found(self):
        """Raises CTFNotFoundError for nonexistent event."""
        from ctf.models import CTFEvent

        with patch.object(CTFEvent, "objects") as mock_objects:
            mock_objects.get.side_effect = CTFEvent.DoesNotExist
            mock_objects.DoesNotExist = CTFEvent.DoesNotExist
            with pytest.raises(CTFNotFoundError):
                range_service.provision_event_ranges(uuid4())

    def test_bulk_provision(self):
        """Bulk provisioning iterates participants without ranges."""
        from ctf.models import CTFEvent

        event_id = uuid4()
        participant_pk = uuid4()
        mock_participant = Mock(pk=participant_pk)

        with (
            patch.object(CTFEvent, "objects") as mock_event_objects,
            patch.object(CTFParticipant, "objects") as mock_part_objects,
            patch.object(
                range_service,
                "provision_participant_range_with_retry",
                return_value={"status": "provisioning", "retries": 0},
            ) as mock_provision,
        ):
            mock_event_objects.get.return_value = Mock()
            mock_part_objects.filter.return_value = [mock_participant]

            result = range_service.provision_event_ranges(event_id)

        assert result["successful"] == 1
        assert result["failed"] == 0
        mock_provision.assert_called_once_with(participant_pk)

    def test_bulk_provision_skips_assigned(self):
        """Participants with existing ranges are skipped (filter handles it)."""
        from ctf.models import CTFEvent

        event_id = uuid4()

        with (
            patch.object(CTFEvent, "objects") as mock_event_objects,
            patch.object(CTFParticipant, "objects") as mock_part_objects,
        ):
            mock_event_objects.get.return_value = Mock()
            mock_part_objects.filter.return_value = []  # No unassigned participants

            result = range_service.provision_event_ranges(event_id)

        assert result["total"] == 0

    def test_bulk_provision_partial_failure(self):
        """Failures in individual provisions are tracked."""
        from ctf.models import CTFEvent

        event_id = uuid4()
        mock_participant = Mock(pk=uuid4())

        with (
            patch.object(CTFEvent, "objects") as mock_event_objects,
            patch.object(CTFParticipant, "objects") as mock_part_objects,
            patch.object(
                range_service,
                "provision_participant_range_with_retry",
                side_effect=RuntimeError("fail"),
            ),
            patch("ctf.services.notification.notify_organizer_provision_failure"),
        ):
            mock_event_objects.get.return_value = Mock()
            mock_part_objects.filter.return_value = [mock_participant]

            result = range_service.provision_event_ranges(event_id)

        assert result["failed"] == 1
        assert result["successful"] == 0


class TestGetRangeStatus:
    """Tests for get_range_status."""

    def test_not_found(self, _patch_participant_not_found):
        """Raises CTFNotFoundError for nonexistent participant."""
        with pytest.raises(CTFNotFoundError):
            range_service.get_range_status(uuid4())

    @pytest.mark.usefixtures("_patch_participant_get")
    def test_not_assigned(self, mock_participant):
        """Returns not_assigned when no range."""
        result = range_service.get_range_status(mock_participant.pk)
        assert result["status"] == "not_assigned"

    @pytest.mark.usefixtures("_patch_participant_get")
    def test_polls_cms(self, mock_participant):
        """Queries CMS for fresh status and updates cache."""
        mock_participant.range_instance_id = 42
        mock_participant.range_status = "provisioning"

        with patch("ctf.bridges.cms_get_range_status", return_value="ready"):
            result = range_service.get_range_status(mock_participant.pk)

        assert result["status"] == "ready"
        assert mock_participant.range_status == "ready"
        mock_participant.save.assert_called_once()


class TestCleanupEventRanges:
    """Tests for cleanup_event_ranges."""

    def test_not_found(self):
        """Raises CTFNotFoundError for nonexistent event."""
        from ctf.models import CTFEvent

        with patch.object(CTFEvent, "objects") as mock_objects:
            mock_objects.get.side_effect = CTFEvent.DoesNotExist
            mock_objects.DoesNotExist = CTFEvent.DoesNotExist
            with pytest.raises(CTFNotFoundError):
                range_service.cleanup_event_ranges(uuid4())

    def test_destroys_ranges(self):
        """Destroys all assigned ranges using participant.user."""
        from ctf.models import CTFEvent

        event_id = uuid4()
        mock_user = Mock()
        mock_participant = Mock(
            pk=uuid4(),
            range_instance_id=42,
            range_status="ready",
            user=mock_user,
        )

        with (
            patch.object(CTFEvent, "objects") as mock_event_objects,
            patch.object(CTFParticipant, "objects") as mock_part_objects,
            patch("ctf.bridges.cms_destroy_range") as mock_destroy,
        ):
            mock_event_objects.get.return_value = Mock()
            mock_part_objects.filter.return_value.select_related.return_value = [mock_participant]

            result = range_service.cleanup_event_ranges(event_id)

        assert result["destroyed"] == 1
        mock_destroy.assert_called_once_with(mock_user, 42)
        mock_participant.save.assert_called_once()
        assert mock_participant.range_instance_id is None
        assert mock_participant.range_status == ""


class TestDestroyParticipantRange:
    """Tests for destroy_participant_range."""

    def test_not_found(self, _patch_participant_not_found):
        """Raises CTFNotFoundError for nonexistent participant."""
        with pytest.raises(CTFNotFoundError):
            range_service.destroy_participant_range(uuid4())

    @pytest.mark.usefixtures("_patch_participant_get")
    def test_no_range(self, mock_participant):
        """Raises CTFRangeError when no range assigned."""
        with pytest.raises(CTFRangeError, match="No range assigned"):
            range_service.destroy_participant_range(mock_participant.pk)

    @pytest.mark.usefixtures("_patch_participant_get")
    def test_destroy_success(self, mock_participant):
        """Successfully destroys a participant's range."""
        mock_participant.range_instance_id = 42
        mock_participant.range_status = "ready"

        with patch("ctf.bridges.cms_destroy_range") as mock_destroy:
            result = range_service.destroy_participant_range(mock_participant.pk)

        assert result["status"] == "destroyed"
        mock_destroy.assert_called_once_with(mock_participant.user, 42)
        mock_participant.save.assert_called_once()
        assert mock_participant.range_instance_id is None


# ---------------------------------------------------------------------------
# Throttled provisioning fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def _patch_event_exists():
    """Patch CTFEvent.objects so .get() succeeds."""
    with patch.object(CTFEvent, "objects") as mock_objects:
        mock_objects.get.return_value = Mock()
        mock_objects.DoesNotExist = CTFEvent.DoesNotExist
        yield mock_objects


@pytest.fixture
def _patch_event_not_found():
    """Patch CTFEvent.objects so .get() raises DoesNotExist."""
    with patch.object(CTFEvent, "objects") as mock_objects:
        mock_objects.get.side_effect = CTFEvent.DoesNotExist
        mock_objects.DoesNotExist = CTFEvent.DoesNotExist
        yield mock_objects


@pytest.fixture
def _patch_sleep():
    """Patch time.sleep to avoid real delays."""
    with patch("ctf.services.range.time.sleep") as mock_sleep:
        yield mock_sleep


@pytest.fixture
def throttle_participants():
    """Create a list of mock participants for throttled provisioning tests."""
    return [Mock(pk=uuid4()) for _ in range(3)]


class TestProvisionEventRangesThrottled:
    """Tests for provision_event_ranges_throttled."""

    def test_not_found(self, _patch_event_not_found):
        """Raises CTFNotFoundError for nonexistent event."""
        with pytest.raises(CTFNotFoundError):
            range_service.provision_event_ranges_throttled(uuid4(), 300)

    @pytest.mark.usefixtures("_patch_event_exists")
    def test_empty_participants(self):
        """Returns zeros when no participants need provisioning."""
        with patch.object(CTFParticipant, "objects") as mock_part:
            mock_part.filter.return_value = []

            result = range_service.provision_event_ranges_throttled(uuid4(), 300)

        assert result["total"] == 0
        assert result["successful"] == 0
        assert result["failed"] == 0
        assert result["interrupted"] is False

    @pytest.mark.usefixtures("_patch_event_exists")
    def test_all_succeed_with_progress(self, throttle_participants, _patch_sleep):
        """Happy path: all provisions succeed, sleeps between them, logs progress."""
        event_id = uuid4()

        with (
            patch.object(CTFParticipant, "objects") as mock_part,
            patch.object(
                range_service,
                "provision_participant_range_with_retry",
                return_value={"status": "provisioning", "retries": 0},
            ) as mock_provision,
            patch("ctf.services.range.logger") as mock_logger,
        ):
            mock_part.filter.return_value = throttle_participants

            result = range_service.provision_event_ranges_throttled(event_id, 300)

        assert result["successful"] == 3
        assert result["failed"] == 0
        assert result["total"] == 3
        assert result["interrupted"] is False
        assert mock_provision.call_count == 3
        # Sleep called between provisions (not after the last one)
        assert _patch_sleep.call_count == 2

        # Verify progress logging (3 progress calls among the info calls)
        progress_calls = [c for c in mock_logger.info.call_args_list if "progress" in str(c.args[0])]
        assert len(progress_calls) == 3
        # First progress: 1/3, last progress: 3/3
        assert progress_calls[0].args[2] == 1  # i + 1
        assert progress_calls[0].args[3] == 3  # count
        assert progress_calls[2].args[2] == 3  # i + 1

    @pytest.mark.usefixtures("_patch_event_exists")
    def test_partial_failure_with_notification(self, throttle_participants, _patch_sleep):
        """Mixed results: tracks errors and notifies organizer."""
        event_id = uuid4()
        call_count = 0

        def provision_side_effect(pk):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("CMS down")
            return {"status": "provisioning", "retries": 0}

        with (
            patch.object(CTFParticipant, "objects") as mock_part,
            patch.object(
                range_service,
                "provision_participant_range_with_retry",
                side_effect=provision_side_effect,
            ),
            patch("ctf.services.notification.notify_organizer_provision_failure") as mock_notify,
        ):
            mock_part.filter.return_value = throttle_participants

            result = range_service.provision_event_ranges_throttled(event_id, 300)

        assert result["successful"] == 2
        assert result["failed"] == 1
        assert len(result["errors"]) == 1
        assert "CMS down" in result["errors"][0]["error"]
        mock_notify.assert_called_once()

    @pytest.mark.usefixtures("_patch_event_exists")
    def test_delay_clamping(self):
        """Delay is clamped to [5, 120] seconds."""
        participants = [Mock(pk=uuid4()) for _ in range(2)]

        # Test floor clamp: window=2s / 2 participants = 1s raw -> clamped to 5s
        # Test ceiling clamp: window=500s / 2 participants = 250s raw -> clamped to 120s
        # Test passthrough: window=100s / 2 participants = 50s raw -> 50s
        for window, expected_delay in [(2, 5.0), (500, 120.0), (100, 50.0)]:
            with (
                patch.object(CTFEvent, "objects") as mock_event,
                patch.object(CTFParticipant, "objects") as mock_part,
                patch.object(
                    range_service,
                    "provision_participant_range_with_retry",
                    return_value={"status": "provisioning", "retries": 0},
                ),
                patch("ctf.services.range.time.sleep") as mock_sleep,
            ):
                mock_event.get.return_value = Mock()
                mock_event.DoesNotExist = CTFEvent.DoesNotExist
                mock_part.filter.return_value = participants

                range_service.provision_event_ranges_throttled(uuid4(), window)

            mock_sleep.assert_called_with(expected_delay)

    @pytest.mark.usefixtures("_patch_event_exists")
    def test_shutdown_interruption(self, _patch_sleep):
        """shutdown_check stops the loop and sets interrupted=True."""
        participants = [Mock(pk=uuid4()) for _ in range(5)]
        check_calls = 0

        def shutdown_after_two():
            nonlocal check_calls
            check_calls += 1
            # shutdown_check is called at the top of each iteration AND
            # before each sleep. After 2 complete iterations that's 4 calls
            # (top + sleep for each). The 5th call (top of i=2) triggers.
            return check_calls >= 5

        with (
            patch.object(CTFParticipant, "objects") as mock_part,
            patch.object(
                range_service,
                "provision_participant_range_with_retry",
                return_value={"status": "provisioning", "retries": 0},
            ) as mock_provision,
        ):
            mock_part.filter.return_value = participants

            result = range_service.provision_event_ranges_throttled(uuid4(), 600, shutdown_check=shutdown_after_two)

        assert result["interrupted"] is True
        # Should have provisioned only 2 before shutdown triggered
        assert mock_provision.call_count == 2
        assert result["successful"] == 2
