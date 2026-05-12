"""Tests for upload token generation and verification.

Tests the HMAC token logic -- no real S3 calls needed.
"""

from unittest.mock import patch

import pytest
from cyberscript.script_context import ScriptExecutionContext

from cms.experiments.s3 import (
    _normalize_script_filename_segment,
    generate_upload_token,
    normalize_legacy_script_s3_key,
    verify_upload_token,
)


class TestUploadToken:
    @patch("cms.experiments.s3.settings")
    def test_roundtrip(self, mock_settings):
        mock_settings.SECRET_KEY = "test-secret-key"
        mock_settings.SCRIPT_UPLOAD_URL_EXPIRES = 600

        token = generate_upload_token(
            user_id=1,
            s3_key="scripts/1/abc_test.py",
            name="Test Script",
            filename="test.py",
            file_size=1024,
        )
        payload = verify_upload_token(token, user_id=1)
        assert payload["user_id"] == 1
        assert payload["s3_key"] == "scripts/1/abc_test.py"
        assert payload["name"] == "Test Script"
        assert payload["filename"] == "test.py"
        assert payload["file_size"] == 1024

    @patch("cms.experiments.s3.settings")
    def test_wrong_user_raises(self, mock_settings):
        mock_settings.SECRET_KEY = "test-secret-key"
        mock_settings.SCRIPT_UPLOAD_URL_EXPIRES = 600

        token = generate_upload_token(
            user_id=1,
            s3_key="scripts/1/x.py",
            name="Test",
            filename="x.py",
            file_size=100,
        )
        with pytest.raises(ValueError, match="user mismatch"):
            verify_upload_token(token, user_id=2)

    @patch("cms.experiments.s3.settings")
    def test_tampered_token_raises(self, mock_settings):
        mock_settings.SECRET_KEY = "test-secret-key"
        mock_settings.SCRIPT_UPLOAD_URL_EXPIRES = 600

        token = generate_upload_token(
            user_id=1,
            s3_key="scripts/1/x.py",
            name="Test",
            filename="x.py",
            file_size=100,
        )
        tampered = token[:-1] + ("a" if token[-1] != "a" else "b")
        with pytest.raises(ValueError, match="signature"):
            verify_upload_token(tampered, user_id=1)

    @patch("cms.experiments.s3.settings")
    def test_invalid_format_raises(self, mock_settings):
        mock_settings.SECRET_KEY = "test-secret-key"
        mock_settings.SCRIPT_UPLOAD_URL_EXPIRES = 600

        with pytest.raises(ValueError, match="format"):
            verify_upload_token("no-dot-separator", user_id=1)

    @patch("cms.experiments.s3.settings")
    def test_expired_token_raises(self, mock_settings):
        mock_settings.SECRET_KEY = "test-secret-key"
        mock_settings.SCRIPT_UPLOAD_URL_EXPIRES = -1

        token = generate_upload_token(
            user_id=1,
            s3_key="scripts/1/x.py",
            name="Test",
            filename="x.py",
            file_size=100,
        )
        with pytest.raises(ValueError, match="expired"):
            verify_upload_token(token, user_id=1)


class TestScriptFilenameNormalization:
    """End-to-end contract: generated S3 keys MUST satisfy the execution validator.

    Bridges `cms.experiments.s3.generate_script_upload_url` and
    `cyberscript.script_context.ScriptExecutionContext` — if an upload
    succeeds, the orchestrator must not later reject the resulting s3_key
    at plan time.
    """

    @pytest.mark.parametrize(
        "filename",
        [
            "simple.py",
            "with spaces and 'quotes'.py",
            "shell;rm -rf /.py",
            "back`ticks`.py",
            "$(injection).py",
            "umlaut-Ümlaut.py",
            "../../etc/passwd",  # path traversal stripped by sanitize_s3_filename
            ".leading-dot.py",
            "x" * 300 + ".py",  # over-length
            "",  # empty
        ],
    )
    def test_normalized_filename_matches_execution_validator(self, filename: str) -> None:
        segment = _normalize_script_filename_segment(filename)
        s3_key = f"scripts/1/abc123_{segment}"
        # If this raises, the upload→execution contract is broken.
        ctx = ScriptExecutionContext(
            script_type="python",
            instance={"name": "Workstation", "instance_id": "i-0abcdef12"},
            script_s3_key=s3_key,
        )
        assert ctx.script_s3_key == s3_key

    def test_unicode_collapses_to_underscore(self) -> None:
        # Leading underscore from the umlaut collapse is stripped by .strip("_").
        assert _normalize_script_filename_segment("Ümlaut.py") == "mlaut.py"

    def test_spaces_collapse_to_underscore(self) -> None:
        assert _normalize_script_filename_segment("with spaces.py") == "with_spaces.py"

    def test_empty_input_falls_back_to_unnamed(self) -> None:
        # sanitize_s3_filename already returns "unnamed" for empty input.
        assert _normalize_script_filename_segment("") == "unnamed"

    def test_only_disallowed_chars_falls_back_to_unnamed(self) -> None:
        assert _normalize_script_filename_segment("'`$();") == "unnamed.py"

    @pytest.mark.parametrize(
        "filename",
        [
            "_.._",  # only underscores around traversal
            "..",  # exact ..
            "x..y",  # buried traversal
            "....",  # cascading
            ".....",  # odd count
            "_.._.._",  # multiple
            "....evil....",  # surrounded
        ],
    )
    def test_traversal_sequences_are_defused(self, filename: str) -> None:
        segment = _normalize_script_filename_segment(filename)
        assert ".." not in segment, f"`{filename}` left `..` in the normalized segment"
        # Confirm the generated key still satisfies the execution validator.
        s3_key = f"scripts/1/abc123_{segment}"
        ctx = ScriptExecutionContext(
            script_type="python",
            instance={"name": "Workstation", "instance_id": "i-0abcdef12"},
            script_s3_key=s3_key,
        )
        assert ctx.script_s3_key == s3_key


class TestNormalizeLegacyScriptS3Key:
    """`normalize_legacy_script_s3_key` powers the 0002 data migration.

    Every output must satisfy `ScriptExecutionContext.script_s3_key` so
    legacy keys that fail today's validator can be renamed in place.
    """

    @pytest.mark.parametrize(
        "legacy_key",
        [
            "scripts/1/abc_my file.py",  # space
            "scripts/1/abc_'quoted'.py",  # quotes
            "scripts/1/abc_$(injection).py",  # command substitution
            "scripts/1/abc_..parent_traversal.py",  # ..
            "scripts/1/abc_back`ticks`.py",  # backticks
            "scripts/1/Ümlaut_file.py",  # unicode
            "/scripts/1/leading_slash.py",  # leading slash
            "scripts/../../etc/passwd",  # traversal
            "scripts/1/" + "x" * 1100,  # over length
        ],
    )
    def test_legacy_keys_normalize_to_valid(self, legacy_key: str) -> None:
        normalized = normalize_legacy_script_s3_key(legacy_key)
        # The contract: the normalized key MUST satisfy ScriptExecutionContext.
        ctx = ScriptExecutionContext(
            script_type="python",
            instance={"name": "Workstation", "instance_id": "i-0abcdef12"},
            script_s3_key=normalized,
        )
        assert ctx.script_s3_key == normalized

    def test_preserves_path_structure(self) -> None:
        assert normalize_legacy_script_s3_key("scripts/1/foo.py") == "scripts/1/foo.py"

    def test_collapses_unicode_to_underscore(self) -> None:
        assert normalize_legacy_script_s3_key("scripts/1/Ümlaut.py") == "scripts/1/mlaut.py"

    def test_strips_leading_slash(self) -> None:
        assert normalize_legacy_script_s3_key("/scripts/1/x.py") == "scripts/1/x.py"

    def test_empty_falls_back_to_unnamed(self) -> None:
        assert normalize_legacy_script_s3_key("") == "unnamed"

    def test_only_disallowed_falls_back_to_unnamed(self) -> None:
        assert normalize_legacy_script_s3_key("'`$();") == "unnamed"

    def test_traversal_is_defused(self) -> None:
        assert ".." not in normalize_legacy_script_s3_key("scripts/../../etc/passwd")
