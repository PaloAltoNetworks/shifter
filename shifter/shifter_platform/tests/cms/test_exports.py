"""Tests for cms module public API exports."""

import cms


class TestCMSExports:
    """Verify cms module exports the expected public API."""

    def test_all_exports_match_declared(self):
        """__all__ should contain all expected public API symbols."""
        expected = {
            "CMSError",
            "cancel_range",
            "cancel_upload",
            "complete_upload",
            "create_agent",
            "create_credential",
            "create_ngfw",
            "create_range",
            "delete_agent",
            "delete_credential",
            "destroy_range",
            "get_active_range",
            "get_agent",
            "get_allowed_extensions",
            "get_credential",
            "get_ngfw",
            "get_range",
            "get_range_by_request_id",
            "get_scenario",
            "get_storage_used",
            "initiate_upload",
            "list_agents",
            "list_credentials",
            "list_ngfws",
            "list_ranges",
            "list_scenarios",
            "pause_range",
            "resume_range",
            "validate_scenario_requirements",
        }
        assert set(cms.__all__) == expected

    def test_all_exports_are_callable_or_exception(self):
        """All exports should be callable functions or exception classes."""
        for name in cms.__all__:
            obj = getattr(cms, name)
            if name == "CMSError":
                assert issubclass(obj, Exception), f"{name} should be an Exception"
            else:
                assert callable(obj), f"{name} should be callable"

    def test_no_private_exports(self):
        """__all__ should not include private symbols."""
        for name in cms.__all__:
            assert not name.startswith("_"), f"Private symbol {name} in __all__"
