"""Tests for environment variable utilities."""


import pytest

from shared.env import get_env, validate_env_vars


class TestValidateEnvVars:
    """Tests for validate_env_vars function."""

    def test_passes_when_all_vars_set(self, monkeypatch):
        """Should pass when all required variables are set."""
        monkeypatch.setenv("VAR1", "value1")
        monkeypatch.setenv("VAR2", "value2")

        # Should not raise
        validate_env_vars(["VAR1", "VAR2"])

    def test_raises_when_var_missing(self, monkeypatch):
        """Should raise EnvironmentError when a variable is missing."""
        monkeypatch.setenv("VAR1", "value1")
        # VAR2 not set

        with pytest.raises(EnvironmentError) as exc_info:
            validate_env_vars(["VAR1", "VAR2"])

        assert "VAR2" in str(exc_info.value)

    def test_raises_when_multiple_vars_missing(self, monkeypatch):
        """Should list all missing variables in error message."""
        # No vars set

        with pytest.raises(EnvironmentError) as exc_info:
            validate_env_vars(["VAR1", "VAR2", "VAR3"])

        error_msg = str(exc_info.value)
        assert "VAR1" in error_msg
        assert "VAR2" in error_msg
        assert "VAR3" in error_msg

    def test_passes_with_empty_list(self):
        """Should pass when no variables are required."""
        # Should not raise
        validate_env_vars([])

    def test_empty_value_is_considered_set(self, monkeypatch):
        """Should pass when variable is set to empty string."""
        monkeypatch.setenv("VAR1", "")

        # Should not raise - empty string is still "set"
        validate_env_vars(["VAR1"])


class TestGetEnv:
    """Tests for get_env function."""

    def test_returns_value_when_set(self, monkeypatch):
        """Should return value when environment variable is set."""
        monkeypatch.setenv("MY_VAR", "my_value")

        result = get_env("MY_VAR")

        assert result == "my_value"

    def test_returns_default_when_not_set(self):
        """Should return default value when variable is not set."""
        result = get_env("NONEXISTENT_VAR", "default_value")

        assert result == "default_value"

    def test_raises_when_required_and_not_set(self):
        """Should raise EnvironmentError when required variable is not set."""
        with pytest.raises(EnvironmentError) as exc_info:
            get_env("NONEXISTENT_VAR")

        assert "NONEXISTENT_VAR" in str(exc_info.value)

    def test_returns_empty_string_when_set_empty(self, monkeypatch):
        """Should return empty string when variable is set to empty."""
        monkeypatch.setenv("EMPTY_VAR", "")

        result = get_env("EMPTY_VAR")

        assert result == ""

    def test_value_overrides_default(self, monkeypatch):
        """Should return actual value even when default is provided."""
        monkeypatch.setenv("MY_VAR", "actual_value")

        result = get_env("MY_VAR", "default_value")

        assert result == "actual_value"
