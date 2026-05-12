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
def mock_s3(settings):
    """Mock S3 operations for CTF file attachments."""
    settings.AWS_S3_BUCKET_NAME = "test-bucket"
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


_PCAP_MAGIC = b"\xd4\xc3\xb2\xa1"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _make_file(content: bytes = b"test file content", name: str = "test.txt"):
    """Create a file-like object for upload testing.

    Default content is plain UTF-8 text and the default name is `.txt`
    (TEXT-category inspection passes for plain text). Tests that exercise a
    specific binary extension must supply a matching magic-byte header.
    """
    f = io.BytesIO(content)
    f.name = name
    return f


def _make_pcap_file(name: str = "capture.pcap"):
    """File-like object whose header is a real libpcap magic prefix."""
    f = io.BytesIO(_PCAP_MAGIC + b"\x00" * 32)
    f.name = name
    return f


class TestAddChallengeFile:
    """Tests for add_challenge_file."""

    def test_upload_success(self, challenge, mock_s3):
        """Valid file upload creates a CTFChallengeFile record."""
        pcap_content = _PCAP_MAGIC + b"\x00" * 32
        file_obj = _make_file(content=pcap_content, name="capture.pcap")
        result = add_challenge_file(
            challenge.id,
            file_obj,
            "capture.pcap",
            display_name="Network Capture",
            actor_id=challenge.event.created_by_id,
        )
        assert result.filename == "capture.pcap"
        assert result.display_name == "Network Capture"
        assert result.file_size_bytes == len(pcap_content)
        assert result.sha256_hash  # non-empty
        assert result.s3_key.startswith("ctf-files/")
        mock_s3.upload_fileobj.assert_called_once()

    def test_upload_sets_order_incrementally(self, challenge, mock_s3):
        """Each uploaded file gets an incrementing order value."""
        f1 = add_challenge_file(challenge.id, _make_file(), "file1.txt", actor_id=challenge.event.created_by_id)
        f2 = add_challenge_file(challenge.id, _make_file(), "file2.txt", actor_id=challenge.event.created_by_id)
        assert f2.order > f1.order

    def test_disallowed_extension_rejected(self, challenge, mock_s3):
        """File with disallowed extension is rejected."""
        with pytest.raises(CTFValidationError, match="not allowed"):
            add_challenge_file(
                challenge.id, _make_file(name="malware.php"), "malware.php", actor_id=challenge.event.created_by_id
            )

    def test_empty_file_rejected(self, challenge, mock_s3):
        """Empty file is rejected."""
        with pytest.raises(CTFValidationError, match="empty"):
            add_challenge_file(challenge.id, _make_file(b""), "empty.txt", actor_id=challenge.event.created_by_id)

    def test_oversized_file_rejected(self, challenge, mock_s3):
        """File exceeding MAX_FILE_SIZE is rejected."""
        from ctf.s3 import MAX_FILE_SIZE

        big_content = b"x" * (MAX_FILE_SIZE + 1)
        with pytest.raises(CTFValidationError, match="exceeds maximum"):
            add_challenge_file(challenge.id, _make_file(big_content), "big.bin", actor_id=challenge.event.created_by_id)

    def test_max_files_per_challenge_enforced(self, challenge, mock_s3):
        """Cannot upload more than MAX_FILES_PER_CHALLENGE files."""
        from ctf.s3 import MAX_FILES_PER_CHALLENGE

        for i in range(MAX_FILES_PER_CHALLENGE):
            add_challenge_file(challenge.id, _make_file(), f"file{i}.txt", actor_id=challenge.event.created_by_id)

        with pytest.raises(CTFValidationError, match="Maximum files"):
            add_challenge_file(challenge.id, _make_file(), "one_more.txt", actor_id=challenge.event.created_by_id)

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
            add_challenge_file(ch.id, _make_file(), "file.txt", actor_id=ch.event.created_by_id)

    def test_nonexistent_challenge_raises_not_found(self, db, mock_s3):
        """Uploading to a nonexistent challenge raises CTFNotFoundError."""
        with pytest.raises(CTFNotFoundError):
            add_challenge_file(uuid4(), _make_file(), "file.txt", actor_id=1)

    def test_magic_byte_mismatch_rejected_before_upload(self, challenge, mock_s3):
        """A .png filename with a PDF magic-byte header is rejected and S3 is not called."""
        bogus_png = io.BytesIO(b"%PDF-1.7\n" + b"\x00" * 32)
        with pytest.raises(CTFValidationError, match="inspection"):
            add_challenge_file(
                challenge.id,
                bogus_png,
                "fake.png",
                actor_id=challenge.event.created_by_id,
            )
        mock_s3.upload_fileobj.assert_not_called()

    def test_text_extension_with_binary_header_rejected(self, challenge, mock_s3):
        """A .txt filename whose body is a PE binary header is rejected."""
        pe_bytes = io.BytesIO(b"MZ\x90\x00" + b"\x00" * 32)
        with pytest.raises(CTFValidationError, match="inspection"):
            add_challenge_file(
                challenge.id,
                pe_bytes,
                "wolf-in-sheep.txt",
                actor_id=challenge.event.created_by_id,
            )
        mock_s3.upload_fileobj.assert_not_called()

    def test_opaque_extension_accepts_arbitrary_bytes(self, challenge, mock_s3):
        """.bin is an OPAQUE category — any byte content is accepted (size still enforced)."""
        opaque = io.BytesIO(b"\xff\xfe\xfd\xfc\x00\x01\x02\x03 random binary blob")
        result = add_challenge_file(
            challenge.id,
            opaque,
            "raw.bin",
            actor_id=challenge.event.created_by_id,
        )
        assert result.filename == "raw.bin"
        mock_s3.upload_fileobj.assert_called_once()

    def test_magic_byte_match_passes(self, challenge, mock_s3):
        """A .png with a real PNG header succeeds."""
        png = io.BytesIO(_PNG_MAGIC + b"\x00" * 32)
        result = add_challenge_file(
            challenge.id,
            png,
            "screenshot.png",
            actor_id=challenge.event.created_by_id,
        )
        assert result.filename == "screenshot.png"
        mock_s3.upload_fileobj.assert_called_once()

    def test_text_extension_with_binary_tail_rejected(self, challenge, mock_s3):
        """Cycle 3 finding 5: a text-prefix + binary-tail upload must fail.

        The bounded header inspection alone would not catch this (the prefix
        is valid UTF-8); the streaming text validator that runs alongside the
        SHA256 loop rejects the binary tail.
        """
        prefix = b"# Looks like a Python file\n" + b" " * 600
        body = prefix + b"\xff\xfe\xfd\xfc binary garbage tail\n"
        bypass = io.BytesIO(body)
        with pytest.raises(CTFValidationError, match="inspection"):
            add_challenge_file(
                challenge.id,
                bypass,
                "smuggle.py",
                actor_id=challenge.event.created_by_id,
            )
        mock_s3.upload_fileobj.assert_not_called()

    def test_text_extension_with_full_utf8_body_succeeds(self, challenge, mock_s3):
        """Streaming validator must accept a clean UTF-8 body."""
        body = ("# valid UTF-8 with multibyte: café résumé\n" * 200).encode("utf-8")
        clean = io.BytesIO(body)
        result = add_challenge_file(
            challenge.id,
            clean,
            "clean.py",
            actor_id=challenge.event.created_by_id,
        )
        assert result.filename == "clean.py"
        mock_s3.upload_fileobj.assert_called_once()


class TestRemoveChallengeFile:
    """Tests for remove_challenge_file."""

    def test_remove_soft_deletes_and_calls_s3(self, challenge, mock_s3):
        """Removing a file soft-deletes the record and calls S3 delete."""
        cf = add_challenge_file(challenge.id, _make_file(), "remove_me.txt", actor_id=challenge.event.created_by_id)
        remove_challenge_file(cf.id, actor_id=cf.challenge.event.created_by_id)

        assert not CTFChallengeFile.objects.filter(pk=cf.id).exists()
        assert CTFChallengeFile.all_objects.filter(pk=cf.id).exists()
        mock_s3.delete_object.assert_called_once()

    def test_remove_nonexistent_raises(self, db, mock_s3):
        """Removing a nonexistent file raises CTFNotFoundError."""
        with pytest.raises(CTFNotFoundError):
            remove_challenge_file(uuid4(), actor_id=1)

    def test_s3_delete_failure_still_soft_deletes(self, challenge, mock_s3):
        """If S3 delete fails, the record is still soft-deleted."""
        from botocore.exceptions import ClientError

        cf = add_challenge_file(challenge.id, _make_file(), "file.txt", actor_id=challenge.event.created_by_id)
        mock_s3.delete_object.side_effect = ClientError(
            {"Error": {"Code": "500", "Message": "S3 error"}}, "DeleteObject"
        )
        # Should not raise — soft delete happens anyway
        remove_challenge_file(cf.id, actor_id=cf.challenge.event.created_by_id)
        assert not CTFChallengeFile.objects.filter(pk=cf.id).exists()


class TestGetChallengeFiles:
    """Tests for get_challenge_files."""

    def test_returns_active_files_ordered(self, challenge, mock_s3):
        """Returns only active (non-deleted) files in order."""
        f1 = add_challenge_file(challenge.id, _make_file(), "first.txt", actor_id=challenge.event.created_by_id)
        f2 = add_challenge_file(challenge.id, _make_file(), "second.txt", actor_id=challenge.event.created_by_id)
        f3 = add_challenge_file(challenge.id, _make_file(), "third.txt", actor_id=challenge.event.created_by_id)
        remove_challenge_file(f2.id, actor_id=f2.challenge.event.created_by_id)

        files = list(get_challenge_files(challenge.id))
        assert len(files) == 2
        assert files[0].id == f1.id
        assert files[1].id == f3.id


class TestGetDownloadUrl:
    """Tests for get_download_url."""

    def test_returns_presigned_url(self, challenge, mock_s3):
        """Returns a presigned S3 URL and filename."""
        cf = add_challenge_file(
            challenge.id,
            _make_pcap_file("download_me.pcap"),
            "download_me.pcap",
            actor_id=challenge.event.created_by_id,
        )
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
        f1 = add_challenge_file(
            challenge.id, _make_file(), "raw.bin", display_name="Memory Dump", actor_id=challenge.event.created_by_id
        )
        assert f1.display == "Memory Dump"

        f2 = add_challenge_file(
            challenge.id, _make_pcap_file("data.pcap"), "data.pcap", actor_id=challenge.event.created_by_id
        )
        assert f2.display == "data.pcap"

    def test_file_size_display(self, challenge, mock_s3):
        """file_size_display returns human-readable size."""
        f = add_challenge_file(
            challenge.id, _make_file(b"x" * 1500), "file.bin", actor_id=challenge.event.created_by_id
        )
        assert "KB" in f.file_size_display

    def test_str_representation(self, challenge, mock_s3):
        """__str__ includes display name and challenge name."""
        f = add_challenge_file(
            challenge.id, _make_file(), "test.bin", display_name="Binary", actor_id=challenge.event.created_by_id
        )
        assert "Binary" in str(f)
        assert challenge.name in str(f)
