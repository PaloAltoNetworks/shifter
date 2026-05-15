"""Tests for server-side header inspection in `complete_script_upload` (issue #696)."""

from contextlib import nullcontext
from unittest.mock import MagicMock, patch

import pytest

from cms.experiments import services
from cms.experiments.exceptions import ScriptUploadError


@pytest.fixture(autouse=True)
def _no_db_transactions():
    """Replace transaction.atomic so the service runs without a DB connection."""
    with (
        patch("cms.experiments.services.transaction") as mock_tx,
        patch("cms.experiments.services._check_result_type"),
    ):
        mock_tx.atomic.return_value = nullcontext()
        yield


@pytest.fixture
def mock_user():
    user = MagicMock()
    user.pk = 7
    user.id = 7
    user.username = "scripter"
    user.is_staff = True
    return user


def _token_payload():
    return {
        "user_id": 7,
        "s3_key": "scripts/7/abc_script.py",
        "name": "My Script",
        "filename": "script.py",
        "file_size": 100,
        "expires_at": 2_000_000_000,
    }


class TestHappyPath:
    def test_text_header_accepted_then_script_saved(self, mock_user):
        with (
            patch("cms.experiments.services.verify_upload_token", return_value=_token_payload()),
            patch("cms.experiments.services.verify_s3_object", return_value=(100, "etag")),
            patch(
                "cms.experiments.services.read_script_header",
                return_value=b"#!/usr/bin/env python3\nprint('ok')\n",
            ),
            patch("cms.experiments.services.delete_s3_object") as mock_delete,
            patch("cms.experiments.services.audit_log") as mock_audit,
            patch("cms.experiments.services.ScriptAsset") as mock_model,
        ):
            mock_instance = MagicMock(pk=42, name="My Script")
            mock_model.return_value = mock_instance
            services.complete_script_upload(mock_user, "token123")
            mock_delete.assert_not_called()
            mock_instance.save.assert_called_once()
            mock_audit.assert_called_once()


class TestBinaryHeaderRejected:
    def test_zip_magic_rejected_and_object_deleted(self, mock_user):
        with (
            patch("cms.experiments.services.verify_upload_token", return_value=_token_payload()),
            patch("cms.experiments.services.verify_s3_object", return_value=(100, "etag")),
            patch(
                "cms.experiments.services.read_script_header",
                return_value=b"\x50\x4b\x03\x04zip-bytes-pretending-to-be-py",
            ),
            patch("cms.experiments.services.delete_s3_object") as mock_delete,
            patch("cms.experiments.services.audit_log") as mock_audit,
            patch("cms.experiments.services.ScriptAsset") as mock_model,
            pytest.raises(ScriptUploadError, match="content"),
        ):
            services.complete_script_upload(mock_user, "token123")
        mock_delete.assert_called_once_with("scripts/7/abc_script.py")
        mock_audit.assert_not_called()
        mock_model.return_value.save.assert_not_called()

    def test_elf_header_rejected_and_object_deleted(self, mock_user):
        with (
            patch("cms.experiments.services.verify_upload_token", return_value=_token_payload()),
            patch("cms.experiments.services.verify_s3_object", return_value=(100, "etag")),
            patch(
                "cms.experiments.services.read_script_header",
                return_value=b"\x7fELF\x02\x01\x01\x00not-python",
            ),
            patch("cms.experiments.services.delete_s3_object") as mock_delete,
            patch("cms.experiments.services.audit_log"),
            patch("cms.experiments.services.ScriptAsset"),
            pytest.raises(ScriptUploadError),
        ):
            services.complete_script_upload(mock_user, "token123")
        mock_delete.assert_called_once_with("scripts/7/abc_script.py")


class TestNonUtf8Rejected:
    def test_non_utf8_header_rejected_and_object_deleted(self, mock_user):
        with (
            patch("cms.experiments.services.verify_upload_token", return_value=_token_payload()),
            patch("cms.experiments.services.verify_s3_object", return_value=(100, "etag")),
            patch(
                "cms.experiments.services.read_script_header",
                return_value=b"\xff\xfe\xfd\xfc garbage",
            ),
            patch("cms.experiments.services.delete_s3_object") as mock_delete,
            patch("cms.experiments.services.audit_log") as mock_audit,
            patch("cms.experiments.services.ScriptAsset") as mock_model,
            pytest.raises(ScriptUploadError),
        ):
            services.complete_script_upload(mock_user, "token123")
        mock_delete.assert_called_once_with("scripts/7/abc_script.py")
        mock_audit.assert_not_called()
        mock_model.return_value.save.assert_not_called()


class TestHeaderReadFailure:
    def test_header_read_s3_error_surfaces_as_script_upload_error(self, mock_user):
        with (
            patch("cms.experiments.services.verify_upload_token", return_value=_token_payload()),
            patch("cms.experiments.services.verify_s3_object", return_value=(100, "etag")),
            patch(
                "cms.experiments.services.read_script_header",
                side_effect=__import__("cms.assets.s3", fromlist=["S3Error"]).S3Error("range failed"),
            ),
            patch("cms.experiments.services.delete_s3_object") as mock_delete,
            patch("cms.experiments.services.audit_log"),
            patch("cms.experiments.services.ScriptAsset"),
            pytest.raises(ScriptUploadError),
        ):
            services.complete_script_upload(mock_user, "token123")
        # Object is not auto-deleted on transport failure (different from a content mismatch).
        mock_delete.assert_not_called()


class TestLoggingDiscipline:
    def test_rejection_log_does_not_leak_header_bytes_or_token(self, mock_user, caplog):
        leak = b"\x50\x4b\x03\x04S3CR3T-DO-NOT-LEAK"
        with (
            patch("cms.experiments.services.verify_upload_token", return_value=_token_payload()),
            patch("cms.experiments.services.verify_s3_object", return_value=(100, "etag")),
            patch("cms.experiments.services.read_script_header", return_value=leak),
            patch("cms.experiments.services.delete_s3_object"),
            patch("cms.experiments.services.audit_log"),
            patch("cms.experiments.services.ScriptAsset"),
            caplog.at_level("WARNING", logger="cms.experiments.services"),
            pytest.raises(ScriptUploadError),
        ):
            services.complete_script_upload(mock_user, "token123")

        combined = " ".join(record.getMessage() for record in caplog.records)
        assert "S3CR3T-DO-NOT-LEAK" not in combined
        assert "token123" not in combined


class TestSizeMismatch:
    """Issue #696 cycle 3 finding 1: actual size must match signed expected size."""

    def test_size_mismatch_rejects_and_deletes_object(self, mock_user):
        payload = _token_payload()
        # Token claims 100 bytes; S3 returned 500 — must reject.
        payload["file_size"] = 100
        with (
            patch("cms.experiments.services.verify_upload_token", return_value=payload),
            patch("cms.experiments.services.verify_s3_object", return_value=(500, "etag")),
            patch("cms.experiments.services.read_script_header") as mock_read,
            patch("cms.experiments.services.delete_s3_object") as mock_delete,
            patch("cms.experiments.services.audit_log"),
            patch("cms.experiments.services.ScriptAsset") as mock_model,
            pytest.raises(ScriptUploadError, match="size mismatch"),
        ):
            services.complete_script_upload(mock_user, "token123")
        mock_delete.assert_called_once_with("scripts/7/abc_script.py")
        # Header read must NOT happen if size already mismatched.
        mock_read.assert_not_called()
        mock_model.return_value.save.assert_not_called()


class TestFullBodyScan:
    """Cycle 3 finding 5: scripts read the full body, not just a header prefix."""

    def test_full_body_is_read_using_max_script_size(self, mock_user, settings):
        settings.SCRIPT_MAX_FILE_SIZE_BYTES = 1024
        body = b"print('hello')\n" + b" " * (1024 - 15)
        with (
            patch("cms.experiments.services.verify_upload_token", return_value=_token_payload()),
            patch("cms.experiments.services.verify_s3_object", return_value=(100, "etag")),
            patch("cms.experiments.services.read_script_header", return_value=body) as mock_read,
            patch("cms.experiments.services.delete_s3_object"),
            patch("cms.experiments.services.audit_log"),
            patch("cms.experiments.services.ScriptAsset") as mock_model,
        ):
            mock_model.return_value = MagicMock(pk=99)
            services.complete_script_upload(mock_user, "token123")
            # max_bytes argument should be SCRIPT_MAX_FILE_SIZE_BYTES, not the
            # smaller UPLOAD_INSPECTION_MAX_HEADER_BYTES.
            _, called_max = mock_read.call_args[0]
            assert called_max == 1024

    def test_text_prefix_with_binary_tail_rejected(self, mock_user):
        # Attacker bypass: valid text prefix followed by binary garbage that
        # never appears in the bounded inspection window. With full-body scan
        # the binary bytes are caught.
        body = b"# innocuous Python prefix\n" + b"\xff\xfe binary garbage\n"
        with (
            patch("cms.experiments.services.verify_upload_token", return_value=_token_payload()),
            patch("cms.experiments.services.verify_s3_object", return_value=(100, "etag")),
            patch("cms.experiments.services.read_script_header", return_value=body),
            patch("cms.experiments.services.delete_s3_object") as mock_delete,
            patch("cms.experiments.services.audit_log"),
            patch("cms.experiments.services.ScriptAsset"),
            pytest.raises(ScriptUploadError),
        ):
            services.complete_script_upload(mock_user, "token123")
        mock_delete.assert_called_once_with("scripts/7/abc_script.py")


class TestBomAccepted:
    def test_bom_prefixed_python_accepted(self, mock_user):
        with (
            patch("cms.experiments.services.verify_upload_token", return_value=_token_payload()),
            patch("cms.experiments.services.verify_s3_object", return_value=(100, "etag")),
            patch(
                "cms.experiments.services.read_script_header",
                return_value=b"\xef\xbb\xbfprint('hi')\n",
            ),
            patch("cms.experiments.services.delete_s3_object") as mock_delete,
            patch("cms.experiments.services.audit_log"),
            patch("cms.experiments.services.ScriptAsset") as mock_model,
        ):
            mock_instance = MagicMock(pk=43)
            mock_model.return_value = mock_instance
            services.complete_script_upload(mock_user, "token123")
            mock_delete.assert_not_called()
            mock_instance.save.assert_called_once()
