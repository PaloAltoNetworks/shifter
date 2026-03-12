"""Tests for CTF Range service."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from ctf.exceptions import CTFNotFoundError, CTFRangeError
from ctf.services import range as range_service


@pytest.mark.django_db
class TestProvisionParticipantRange:
    """Tests for provision_participant_range."""

    def test_not_found(self):
        """Raises CTFNotFoundError for nonexistent participant."""
        with pytest.raises(CTFNotFoundError):
            range_service.provision_participant_range(uuid4())

    def test_already_assigned(self, ctf_participant):
        """Raises CTFRangeError if participant already has a range."""
        ctf_participant.range_instance_id = 42
        ctf_participant.save(update_fields=["range_instance_id"])

        with pytest.raises(CTFRangeError, match="already has a range"):
            range_service.provision_participant_range(ctf_participant.pk)

    def test_provision_success(self, ctf_participant, participant_user):
        """Successful provisioning sets range_instance_id and status using participant.user."""
        mock_result = MagicMock()
        mock_result.request_id = uuid4()

        mock_range_instance = MagicMock()
        mock_range_instance.pk = 99

        with (
            patch("cms.services.create_range", return_value=mock_result) as mock_create,
            patch(
                "cms.models.RangeInstance.objects.filter",
                return_value=MagicMock(first=MagicMock(return_value=mock_range_instance)),
            ),
        ):
            result = range_service.provision_participant_range(ctf_participant.pk)

        assert result["status"] == "provisioning"
        ctf_participant.refresh_from_db()
        assert ctf_participant.range_status == "provisioning"
        # Verify range is created under participant's user, not the organizer
        mock_create.assert_called_once()
        assert mock_create.call_args.kwargs["user"] == participant_user

    def test_provision_requires_registered_user(self, ctf_participant_invited):
        """Raises CTFRangeError if participant has no linked user."""
        with pytest.raises(CTFRangeError, match="must be registered"):
            range_service.provision_participant_range(ctf_participant_invited.pk)

    def test_provision_cms_failure(self, ctf_participant):
        """CMS errors are wrapped in CTFRangeError."""
        with (
            patch("cms.services.create_range", side_effect=RuntimeError("CMS down")),
            pytest.raises(CTFRangeError, match="Range provisioning failed"),
        ):
            range_service.provision_participant_range(ctf_participant.pk)


@pytest.mark.django_db
class TestProvisionEventRanges:
    """Tests for provision_event_ranges."""

    def test_not_found(self):
        """Raises CTFNotFoundError for nonexistent event."""
        with pytest.raises(CTFNotFoundError):
            range_service.provision_event_ranges(uuid4())

    def test_bulk_provision(self, ctf_event, ctf_participant):
        """Bulk provisioning iterates participants without ranges."""
        with patch.object(
            range_service,
            "provision_participant_range",
            return_value={"status": "provisioning"},
        ) as mock_provision:
            result = range_service.provision_event_ranges(ctf_event.pk)

        assert result["successful"] == 1
        assert result["failed"] == 0
        mock_provision.assert_called_once_with(ctf_participant.pk)

    def test_bulk_provision_skips_assigned(self, ctf_event, ctf_participant):
        """Participants with existing ranges are skipped."""
        ctf_participant.range_instance_id = 42
        ctf_participant.save(update_fields=["range_instance_id"])

        result = range_service.provision_event_ranges(ctf_event.pk)
        assert result["total"] == 0

    def test_bulk_provision_partial_failure(self, ctf_event, ctf_participant):
        """Failures in individual provisions are tracked."""
        with patch.object(
            range_service,
            "provision_participant_range",
            side_effect=RuntimeError("fail"),
        ):
            result = range_service.provision_event_ranges(ctf_event.pk)

        assert result["failed"] == 1
        assert result["successful"] == 0


@pytest.mark.django_db
class TestGetRangeStatus:
    """Tests for get_range_status."""

    def test_not_found(self):
        """Raises CTFNotFoundError for nonexistent participant."""
        with pytest.raises(CTFNotFoundError):
            range_service.get_range_status(uuid4())

    def test_not_assigned(self, ctf_participant):
        """Returns not_assigned when no range."""
        result = range_service.get_range_status(ctf_participant.pk)
        assert result["status"] == "not_assigned"

    def test_polls_cms(self, ctf_participant):
        """Queries CMS for fresh status and updates cache."""
        ctf_participant.range_instance_id = 42
        ctf_participant.range_status = "provisioning"
        ctf_participant.save(update_fields=["range_instance_id", "range_status"])

        mock_instance = MagicMock()
        mock_instance.status = "ready"

        with patch("cms.models.RangeInstance.objects.get", return_value=mock_instance):
            result = range_service.get_range_status(ctf_participant.pk)

        assert result["status"] == "ready"
        ctf_participant.refresh_from_db()
        assert ctf_participant.range_status == "ready"


@pytest.mark.django_db
class TestGetRangeAccessUrl:
    """Tests for get_range_access_url."""

    def test_not_found(self):
        """Raises CTFNotFoundError for nonexistent participant."""
        with pytest.raises(CTFNotFoundError):
            range_service.get_range_access_url(uuid4())

    def test_no_range(self, ctf_participant):
        """Raises CTFRangeError when no range assigned."""
        with pytest.raises(CTFRangeError, match="No range assigned"):
            range_service.get_range_access_url(ctf_participant.pk)

    def test_range_not_ready(self, ctf_participant):
        """Raises CTFRangeError when range not ready."""
        ctf_participant.range_instance_id = 42
        ctf_participant.range_status = "provisioning"
        ctf_participant.save(update_fields=["range_instance_id", "range_status"])

        with pytest.raises(CTFRangeError, match="not ready"):
            range_service.get_range_access_url(ctf_participant.pk)

    def test_generates_url(self, ctf_participant):
        """Returns Guacamole URL when range is ready."""
        ctf_participant.range_instance_id = 42
        ctf_participant.range_status = "ready"
        ctf_participant.save(update_fields=["range_instance_id", "range_status"])

        mock_instance = MagicMock()
        mock_instance.range_spec = {"subnets": [{"instances": [{"private_ip": "10.0.1.5"}]}]}

        with (
            patch("cms.models.RangeInstance.objects.get", return_value=mock_instance),
            patch(
                "mission_control.guacamole.create_guacamole_rdp_url",
                return_value="https://guac.example.com/session",
            ) as mock_guac,
        ):
            url = range_service.get_range_access_url(ctf_participant.pk)

        assert url == "https://guac.example.com/session"
        mock_guac.assert_called_once()


@pytest.mark.django_db
class TestCleanupEventRanges:
    """Tests for cleanup_event_ranges."""

    def test_not_found(self):
        """Raises CTFNotFoundError for nonexistent event."""
        with pytest.raises(CTFNotFoundError):
            range_service.cleanup_event_ranges(uuid4())

    def test_destroys_ranges(self, ctf_event, ctf_participant, participant_user):
        """Destroys all assigned ranges using participant.user."""
        ctf_participant.range_instance_id = 42
        ctf_participant.range_status = "ready"
        ctf_participant.save(update_fields=["range_instance_id", "range_status"])

        with patch("cms.services.destroy_range") as mock_destroy:
            result = range_service.cleanup_event_ranges(ctf_event.pk)

        assert result["destroyed"] == 1
        mock_destroy.assert_called_once_with(participant_user, 42)
        ctf_participant.refresh_from_db()
        assert ctf_participant.range_instance_id is None
        assert ctf_participant.range_status == ""


@pytest.mark.django_db
class TestDestroyParticipantRange:
    """Tests for destroy_participant_range."""

    def test_not_found(self):
        """Raises CTFNotFoundError for nonexistent participant."""
        with pytest.raises(CTFNotFoundError):
            range_service.destroy_participant_range(uuid4())

    def test_no_range(self, ctf_participant):
        """Raises CTFRangeError when no range assigned."""
        with pytest.raises(CTFRangeError, match="No range assigned"):
            range_service.destroy_participant_range(ctf_participant.pk)

    def test_destroy_success(self, ctf_participant, participant_user):
        """Successfully destroys a participant's range using participant.user."""
        ctf_participant.range_instance_id = 42
        ctf_participant.range_status = "ready"
        ctf_participant.save(update_fields=["range_instance_id", "range_status"])

        with patch("cms.services.destroy_range") as mock_destroy:
            result = range_service.destroy_participant_range(ctf_participant.pk)

        assert result["status"] == "destroyed"
        mock_destroy.assert_called_once_with(participant_user, 42)
        ctf_participant.refresh_from_db()
        assert ctf_participant.range_instance_id is None


@pytest.mark.django_db
class TestExtractIpFromRangeSpec:
    """Tests for _extract_ip_from_range_spec helper."""

    def test_new_format(self):
        """Extracts IP from subnets format."""
        spec = {"subnets": [{"instances": [{"private_ip": "10.0.1.5"}]}]}
        assert range_service._extract_ip_from_range_spec(spec) == "10.0.1.5"

    def test_legacy_format(self):
        """Extracts IP from legacy instances format."""
        spec = {"instances": [{"private_ip": "192.168.1.10"}]}
        assert range_service._extract_ip_from_range_spec(spec) == "192.168.1.10"

    def test_none_spec(self):
        """Returns None for None spec."""
        assert range_service._extract_ip_from_range_spec(None) is None

    def test_empty_spec(self):
        """Returns None for empty spec."""
        assert range_service._extract_ip_from_range_spec({}) is None
