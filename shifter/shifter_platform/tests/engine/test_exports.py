"""Tests for engine module public API exports."""


class TestEngineExports:
    """Verify engine module exports the expected public API."""

    def test_exports_engine_error(self):
        """EngineError exception should be importable from engine."""
        from engine import EngineError

        assert issubclass(EngineError, Exception)

    def test_exports_create_range(self):
        """create_range should be importable from engine."""
        from engine import create_range

        assert callable(create_range)

    def test_exports_destroy_range(self):
        """destroy_range should be importable from engine."""
        from engine import destroy_range

        assert callable(destroy_range)

    def test_exports_cancel_range(self):
        """cancel_range should be importable from engine."""
        from engine import cancel_range

        assert callable(cancel_range)

    def test_exports_get_range_status(self):
        """get_range_status should be importable from engine."""
        from engine import get_range_status

        assert callable(get_range_status)

    def test_exports_pause_range(self):
        """pause_range should be importable from engine."""
        from engine import pause_range

        assert callable(pause_range)

    def test_exports_resume_range(self):
        """resume_range should be importable from engine."""
        from engine import resume_range

        assert callable(resume_range)

    def test_exports_connect_terminal(self):
        """connect_terminal should be importable from engine."""
        from engine import connect_terminal

        assert callable(connect_terminal)

    def test_all_exports_match_declared(self):
        """__all__ should match actual exports."""
        import engine

        expected = {
            "EngineError",
            "cancel_range",
            "connect_terminal",
            "create_range",
            "destroy_range",
            "get_range_status",
            "pause_range",
            "resume_range",
        }
        assert set(engine.__all__) == expected

    def test_no_private_exports(self):
        """__all__ should not include private symbols."""
        import engine

        for name in engine.__all__:
            assert not name.startswith("_"), f"Private symbol {name} in __all__"
