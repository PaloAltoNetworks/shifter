"""Tests for CTF challenge file attachments.

Covers:
- Upload, download ACL, file limits, soft delete, event state checks
- S3 operations are mocked following existing test patterns
"""

from __future__ import annotations

import io
from datetime import timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from django.utils import timezone

from ctf.enums import ChallengeCategory, ChallengeDifficulty, EventStatus
from ctf.exceptions import CTFNotFoundError, CTFStateError, CTFValidationError
from ctf.models import CTFChallenge, CTFChallengeFile, CTFEvent
from ctf.services.attachment import (
    add_challenge_file,
    get_challenge_files,
    get_download_url,
    remove_challenge_file,
)


@pytest.fixture
def mock_s3():
    """Mock S3 operations for CTF file attachments."""
    mock_client = MagicMock()
    mock_client.generate_presigned_url.return_value = (
        "https://s3.us-east-2.amazonaws.com/bucket/key?X-Amz-Signature=test"
    )
    with patch("ctf.s3.get_s3_client", return_value=mock_client):
        yield mock_client


@pytest.fixture
def draft_event(db, organizer_user):
    """Draft event for file attachment testing."""
    return CTFEvent.objects.create(
        name="File Test Event",
        description="Event for file testing",
        created_by=organizer_user,
        status=EventStatus.DRAFT.value,
        event_start=timezone.now() + timedelta(days=7),
        event_end=timezone.now() + timedelta(days=7, hours=8),
        scenario_id="basic",
    )


@pytest.fixture
def challenge(db, draft_event):
    """Challenge to attach files to."""
    return CTFChallenge.objects.create(
        event=draft_event,
        name="File Test Challenge",
        description="Challenge with files",
        category=ChallengeCategory.FORENSICS.value,
        points=200,
        difficulty=ChallengeDifficulty.MEDIUM.value,
        flag_hash="$2b$12$hash_file_test",
    )


def _make_file(content: bytes = b"test file content", name: str = "test.pcap"):
    """Create a file-like object for upload testing."""
    f = io.BytesIO(content)
    f.name = name
    return f


class TestAddChallengeFile:
    """Tests for add_challenge_file."""

    def test_upload_success(self, challenge, mock_s3):
        """Valid file upload creates a CTFChallengeFile record."""
        file_obj = _make_file()
        result = add_challenge_file(challenge.id, file_obj, "capture.pcap", display_name="Network Capture")
        assert result.filename == "capture.pcap"
        assert result.display_name == "Network Capture"
        assert result.file_size_bytes == len(b"test file content")
        assert result.sha256_hash  # non-empty
        assert result.s3_key.startswith("ctf-files/")
        mock_s3.upload_fileobj.assert_called_once()

    def test_upload_sets_order_incrementally(self, challenge, mock_s3):
        """Each uploaded file gets an incrementing order value."""
        f1 = add_challenge_file(challenge.id, _make_file(), "file1.txt")
        f2 = add_challenge_file(challenge.id, _make_file(), "file2.txt")
        assert f2.order > f1.order

    def test_disallowed_extension_rejected(self, challenge, mock_s3):
        """File with disallowed extension is rejected."""
        with pytest.raises(CTFValidationError, match="not allowed"):
            add_challenge_file(challenge.id, _make_file(name="malware.php"), "malware.php")

    def test_empty_file_rejected(self, challenge, mock_s3):
        """Empty file is rejected."""
        with pytest.raises(CTFValidationError, match="empty"):
            add_challenge_file(challenge.id, _make_file(b""), "empty.txt")

    def test_oversized_file_rejected(self, challenge, mock_s3):
        """File exceeding MAX_FILE_SIZE is rejected."""
        from ctf.s3 import MAX_FILE_SIZE

        big_content = b"x" * (MAX_FILE_SIZE + 1)
        with pytest.raises(CTFValidationError, match="exceeds maximum"):
            add_challenge_file(challenge.id, _make_file(big_content), "big.bin")

    def test_max_files_per_challenge_enforced(self, challenge, mock_s3):
        """Cannot upload more than MAX_FILES_PER_CHALLENGE files."""
        from ctf.s3 import MAX_FILES_PER_CHALLENGE

        for i in range(MAX_FILES_PER_CHALLENGE):
            add_challenge_file(challenge.id, _make_file(), f"file{i}.txt")

        with pytest.raises(CTFValidationError, match="Maximum files"):
            add_challenge_file(challenge.id, _make_file(), "one_more.txt")

    def test_non_modifiable_event_rejected(self, organizer_user, mock_s3):
        """Cannot upload files when event is not content-modifiable."""
        active_event = CTFEvent.objects.create(
            name="Active Event",
            description="Active",
            created_by=organizer_user,
            status=EventStatus.ACTIVE.value,
            event_start=timezone.now() - timedelta(hours=1),
            event_end=timezone.now() + timedelta(hours=7),
            scenario_id="basic",
        )
        ch = CTFChallenge.objects.create(
            event=active_event,
            name="Active Challenge",
            description="Active",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="$2b$12$hash_active",
        )
        with pytest.raises(CTFStateError):
            add_challenge_file(ch.id, _make_file(), "file.txt")

    def test_nonexistent_challenge_raises_not_found(self, db, mock_s3):
        """Uploading to a nonexistent challenge raises CTFNotFoundError."""
        with pytest.raises(CTFNotFoundError):
            add_challenge_file(uuid4(), _make_file(), "file.txt")


class TestRemoveChallengeFile:
    """Tests for remove_challenge_file."""

    def test_remove_soft_deletes_and_calls_s3(self, challenge, mock_s3):
        """Removing a file soft-deletes the record and calls S3 delete."""
        cf = add_challenge_file(challenge.id, _make_file(), "remove_me.txt")
        remove_challenge_file(cf.id)

        assert not CTFChallengeFile.objects.filter(pk=cf.id).exists()
        assert CTFChallengeFile.all_objects.filter(pk=cf.id).exists()
        mock_s3.delete_object.assert_called_once()

    def test_remove_nonexistent_raises(self, db, mock_s3):
        """Removing a nonexistent file raises CTFNotFoundError."""
        with pytest.raises(CTFNotFoundError):
            remove_challenge_file(uuid4())

    def test_s3_delete_failure_still_soft_deletes(self, challenge, mock_s3):
        """If S3 delete fails, the record is still soft-deleted."""
        from botocore.exceptions import ClientError

        cf = add_challenge_file(challenge.id, _make_file(), "file.txt")
        mock_s3.delete_object.side_effect = ClientError(
            {"Error": {"Code": "500", "Message": "S3 error"}}, "DeleteObject"
        )
        # Should not raise — soft delete happens anyway
        remove_challenge_file(cf.id)
        assert not CTFChallengeFile.objects.filter(pk=cf.id).exists()


class TestGetChallengeFiles:
    """Tests for get_challenge_files."""

    def test_returns_active_files_ordered(self, challenge, mock_s3):
        """Returns only active (non-deleted) files in order."""
        f1 = add_challenge_file(challenge.id, _make_file(), "first.txt")
        f2 = add_challenge_file(challenge.id, _make_file(), "second.txt")
        f3 = add_challenge_file(challenge.id, _make_file(), "third.txt")
        remove_challenge_file(f2.id)

        files = list(get_challenge_files(challenge.id))
        assert len(files) == 2
        assert files[0].id == f1.id
        assert files[1].id == f3.id


class TestGetDownloadUrl:
    """Tests for get_download_url."""

    def test_returns_presigned_url(self, challenge, mock_s3):
        """Returns a presigned S3 URL and filename."""
        cf = add_challenge_file(challenge.id, _make_file(), "download_me.pcap")
        url, filename = get_download_url(cf.id)
        assert "amazonaws.com" in url
        assert filename == "download_me.pcap"

    def test_nonexistent_file_raises(self, db, mock_s3):
        """Requesting URL for nonexistent file raises CTFNotFoundError."""
        with pytest.raises(CTFNotFoundError):
            get_download_url(uuid4())


class TestCTFChallengeFileModel:
    """Tests for CTFChallengeFile model properties."""

    def test_display_property(self, challenge, mock_s3):
        """display returns display_name if set, otherwise filename."""
        f1 = add_challenge_file(challenge.id, _make_file(), "raw.bin", display_name="Memory Dump")
        assert f1.display == "Memory Dump"

        f2 = add_challenge_file(challenge.id, _make_file(), "data.pcap")
        assert f2.display == "data.pcap"

    def test_file_size_display(self, challenge, mock_s3):
        """file_size_display returns human-readable size."""
        f = add_challenge_file(challenge.id, _make_file(b"x" * 1500), "file.bin")
        assert "KB" in f.file_size_display

    def test_str_representation(self, challenge, mock_s3):
        """__str__ includes display name and challenge name."""
        f = add_challenge_file(challenge.id, _make_file(), "test.bin", display_name="Binary")
        assert "Binary" in str(f)
        assert challenge.name in str(f)
