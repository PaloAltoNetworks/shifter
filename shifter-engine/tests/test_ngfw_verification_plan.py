"""Tests for NGFWVerificationPlan - TDD: Write tests first, all must fail initially.

NGFWVerificationPlan verifies that VM-Series has successfully registered
with Strata Cloud Manager (SCM).
"""

import pytest


class TestNGFWVerificationPlanImports:
    """Test that NGFWVerificationPlan can be imported."""

    def test_import_ngfw_verification_plan(self):
        """NGFWVerificationPlan should be importable."""
        from plans.ngfw_verification import NGFWVerificationPlan

        assert NGFWVerificationPlan is not None


class TestNGFWVerificationPlanStructure:
    """Test NGFWVerificationPlan structure."""

    def test_has_empty_steps_list(self):
        """Plan should have empty steps list (no setup needed)."""
        from plans.ngfw_verification import NGFWVerificationPlan

        plan = NGFWVerificationPlan()
        assert plan.steps == []

    def test_has_verify_step(self):
        """Plan should have a verification step."""
        from plans.ngfw_verification import NGFWVerificationPlan

        plan = NGFWVerificationPlan()
        assert plan.verify_step is not None
        assert plan.verify_step.name == "verify_scm_registration"

    def test_verify_step_uses_panorama_status_command(self):
        """Verification step should run 'show panorama-status'."""
        from plans.ngfw_verification import NGFWVerificationPlan

        plan = NGFWVerificationPlan()
        assert "show panorama-status" in plan.verify_step.script

    def test_verify_step_is_verification_type(self):
        """Verification step should be marked as verification."""
        from plans.ngfw_verification import NGFWVerificationPlan

        plan = NGFWVerificationPlan()
        assert plan.verify_step.is_verification is True


class TestGetContext:
    """Test get_context method."""

    def test_get_context_returns_dict(self):
        """get_context should return a dictionary."""
        from plans.ngfw_verification import NGFWVerificationPlan

        plan = NGFWVerificationPlan()

        class MockInstance:
            pass

        result = plan.get_context(MockInstance())
        assert isinstance(result, dict)

    def test_get_context_empty_for_verification(self):
        """get_context should return empty dict (no template vars needed)."""
        from plans.ngfw_verification import NGFWVerificationPlan

        plan = NGFWVerificationPlan()

        class MockInstance:
            pass

        result = plan.get_context(MockInstance())
        assert result == {}


class TestParsePanoramaStatus:
    """Test parse_panorama_status static method."""

    def test_parse_connected_status(self):
        """Parse successful connection output."""
        from plans.ngfw_verification import NGFWVerificationPlan

        output = """
        Panorama Server 1 : cloud
            Connected     : yes
            HA state      : n/a
        """
        status = NGFWVerificationPlan.parse_panorama_status(output)

        assert status["connected"] is True
        assert status["server"] == "cloud"

    def test_parse_disconnected_status(self):
        """Parse failed connection output."""
        from plans.ngfw_verification import NGFWVerificationPlan

        output = """
        Panorama Server 1 : cloud
            Connected     : no
        """
        status = NGFWVerificationPlan.parse_panorama_status(output)

        assert status["connected"] is False

    def test_parse_empty_output(self):
        """Parse empty output returns defaults."""
        from plans.ngfw_verification import NGFWVerificationPlan

        status = NGFWVerificationPlan.parse_panorama_status("")

        assert status["connected"] is False
        assert status["server"] is None

    def test_parse_malformed_output(self):
        """Parse malformed output returns defaults."""
        from plans.ngfw_verification import NGFWVerificationPlan

        output = "Some random text that doesn't match expected format"
        status = NGFWVerificationPlan.parse_panorama_status(output)

        assert status["connected"] is False
        assert status["server"] is None

    def test_parse_server_with_ip(self):
        """Parse server line with IP address."""
        from plans.ngfw_verification import NGFWVerificationPlan

        output = """
        Panorama Server 1 : 192.168.1.100
            Connected     : yes
        """
        status = NGFWVerificationPlan.parse_panorama_status(output)

        assert status["server"] == "192.168.1.100"
        assert status["connected"] is True


class TestIsRegistered:
    """Test is_registered static method."""

    def test_is_registered_true_when_connected(self):
        """is_registered returns True when connected."""
        from plans.ngfw_verification import NGFWVerificationPlan

        output = "Connected     : yes"
        assert NGFWVerificationPlan.is_registered(output) is True

    def test_is_registered_false_when_disconnected(self):
        """is_registered returns False when not connected."""
        from plans.ngfw_verification import NGFWVerificationPlan

        output = "Connected     : no"
        assert NGFWVerificationPlan.is_registered(output) is False

    def test_is_registered_false_on_empty(self):
        """is_registered returns False on empty output."""
        from plans.ngfw_verification import NGFWVerificationPlan

        assert NGFWVerificationPlan.is_registered("") is False

    def test_is_registered_case_insensitive(self):
        """is_registered is case insensitive."""
        from plans.ngfw_verification import NGFWVerificationPlan

        assert NGFWVerificationPlan.is_registered("CONNECTED: YES") is True
        assert NGFWVerificationPlan.is_registered("connected: YES") is True


class TestRetryLogic:
    """Test retry on verification failure."""

    def test_max_retries_attribute(self):
        """Plan should have max_retries attribute."""
        from plans.ngfw_verification import NGFWVerificationPlan

        plan = NGFWVerificationPlan()
        assert hasattr(plan, "max_retries")
        assert plan.max_retries == 1  # Retry once then fail

    def test_retry_delay_attribute(self):
        """Plan should have retry_delay_seconds attribute."""
        from plans.ngfw_verification import NGFWVerificationPlan

        plan = NGFWVerificationPlan()
        assert hasattr(plan, "retry_delay_seconds")
        assert plan.retry_delay_seconds == 60  # 1 minute between retries
