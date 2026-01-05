"""Tests for cms module public API exports."""


class TestCMSExports:
    """Verify cms module exports the expected public API."""

    # --- Exception export ---

    def test_exports_cms_error(self):
        """CMSError exception should be importable from cms."""
        from cms import CMSError

        assert issubclass(CMSError, Exception)

    # --- Agent service exports ---

    def test_exports_create_agent(self):
        """create_agent should be importable from cms."""
        from cms import create_agent

        assert callable(create_agent)

    def test_exports_delete_agent(self):
        """delete_agent should be importable from cms."""
        from cms import delete_agent

        assert callable(delete_agent)

    def test_exports_list_agents(self):
        """list_agents should be importable from cms."""
        from cms import list_agents

        assert callable(list_agents)

    def test_exports_get_agent(self):
        """get_agent should be importable from cms."""
        from cms import get_agent

        assert callable(get_agent)

    def test_exports_get_allowed_extensions(self):
        """get_allowed_extensions should be importable from cms."""
        from cms import get_allowed_extensions

        assert callable(get_allowed_extensions)

    # --- Credential service exports ---

    def test_exports_create_credential(self):
        """create_credential should be importable from cms."""
        from cms import create_credential

        assert callable(create_credential)

    def test_exports_delete_credential(self):
        """delete_credential should be importable from cms."""
        from cms import delete_credential

        assert callable(delete_credential)

    def test_exports_list_credentials(self):
        """list_credentials should be importable from cms."""
        from cms import list_credentials

        assert callable(list_credentials)

    def test_exports_get_credential(self):
        """get_credential should be importable from cms."""
        from cms import get_credential

        assert callable(get_credential)

    # --- Range service exports ---

    def test_exports_list_ranges(self):
        """list_ranges should be importable from cms."""
        from cms import list_ranges

        assert callable(list_ranges)

    def test_exports_get_range(self):
        """get_range should be importable from cms."""
        from cms import get_range

        assert callable(get_range)

    def test_exports_get_active_range(self):
        """get_active_range should be importable from cms."""
        from cms import get_active_range

        assert callable(get_active_range)

    def test_exports_create_range(self):
        """create_range should be importable from cms."""
        from cms import create_range

        assert callable(create_range)

    def test_exports_destroy_range(self):
        """destroy_range should be importable from cms."""
        from cms import destroy_range

        assert callable(destroy_range)

    def test_exports_cancel_range(self):
        """cancel_range should be importable from cms."""
        from cms import cancel_range

        assert callable(cancel_range)

    def test_exports_pause_range(self):
        """pause_range should be importable from cms."""
        from cms import pause_range

        assert callable(pause_range)

    def test_exports_resume_range(self):
        """resume_range should be importable from cms."""
        from cms import resume_range

        assert callable(resume_range)

    # --- Upload service exports ---

    def test_exports_initiate_upload(self):
        """initiate_upload should be importable from cms."""
        from cms import initiate_upload

        assert callable(initiate_upload)

    def test_exports_complete_upload(self):
        """complete_upload should be importable from cms."""
        from cms import complete_upload

        assert callable(complete_upload)

    def test_exports_cancel_upload(self):
        """cancel_upload should be importable from cms."""
        from cms import cancel_upload

        assert callable(cancel_upload)

    # --- Storage service exports ---

    def test_exports_get_storage_used(self):
        """get_storage_used should be importable from cms."""
        from cms import get_storage_used

        assert callable(get_storage_used)

    # --- Scenario service exports ---

    def test_exports_list_scenarios(self):
        """list_scenarios should be importable from cms."""
        from cms import list_scenarios

        assert callable(list_scenarios)

    def test_exports_get_scenario(self):
        """get_scenario should be importable from cms."""
        from cms import get_scenario

        assert callable(get_scenario)

    def test_exports_validate_scenario_requirements(self):
        """validate_scenario_requirements should be importable from cms."""
        from cms import validate_scenario_requirements

        assert callable(validate_scenario_requirements)

    # --- __all__ verification ---

    def test_all_exports_match_declared(self):
        """__all__ should match actual exports."""
        import cms

        expected = {
            "CMSError",
            "cancel_range",
            "cancel_upload",
            "complete_upload",
            "create_agent",
            "create_credential",
            "create_range",
            "delete_agent",
            "delete_credential",
            "destroy_range",
            "get_active_range",
            "get_agent",
            "get_allowed_extensions",
            "get_credential",
            "get_range",
            "get_scenario",
            "get_storage_used",
            "initiate_upload",
            "list_agents",
            "list_credentials",
            "list_ranges",
            "list_scenarios",
            "pause_range",
            "resume_range",
            "validate_scenario_requirements",
        }
        assert set(cms.__all__) == expected

    def test_no_private_exports(self):
        """__all__ should not include private symbols."""
        import cms

        for name in cms.__all__:
            assert not name.startswith("_"), f"Private symbol {name} in __all__"
