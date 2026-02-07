"""Tests for engine module public API exports."""


class TestEngineExports:
    """Verify engine module exports the expected public API."""

    def test_exports_engine_error(self):
        """EngineError exception should be importable from engine."""
        from engine import EngineError

        assert issubclass(EngineError, Exception)

    def test_all_exports_match_declared(self):
        """__all__ should match actual exports."""
        import engine

        expected = {
            "EngineError",
            "cancel_range",
            "cancel_range_by_request",
            "connect_ngfw_terminal",
            "connect_terminal",
            "create_ngfw",
            "create_range",
            "destroy_ngfw",
            "destroy_range",
            "destroy_range_by_request",
            "get_ngfw_gui_info",
            "get_range_ngfw_context",
            "get_range_status",
            "pause_range",
            "resume_range",
            "start_ngfw",
            "stop_ngfw",
        }
        assert set(engine.__all__) == expected

    def test_no_private_exports(self):
        """__all__ should not include private symbols."""
        import engine

        for name in engine.__all__:
            assert not name.startswith("_"), f"Private symbol {name} in __all__"
