"""Tests for mission_control.upload_session module."""

import time

from mission_control.upload_session import (
    UPLOAD_LOCK_TIMEOUT,
    check_upload_in_progress,
    set_upload_in_progress,
    upload_lock_matches_token,
    upload_token_fingerprint,
)


class MockSession(dict):
    """Mock Django session for testing."""

    def pop(self, key, default=None):
        try:
            return dict.pop(self, key)
        except KeyError:
            return default


# -----------------------------------------------------------------------------
# Tests for check_upload_in_progress()
# -----------------------------------------------------------------------------


class TestCheckUploadInProgress:
    """Tests for check_upload_in_progress function."""

    def test_returns_false_when_no_lock(self):
        """Should return False when session has no upload_lock."""
        session = MockSession()
        assert check_upload_in_progress(session) is False

    def test_returns_true_when_locked(self):
        """Should return True when session has valid upload_lock."""
        session = MockSession()
        session["upload_lock"] = {"started_at": time.time()}

        assert check_upload_in_progress(session) is True

    def test_returns_false_when_lock_expired(self):
        """Should return False when lock has expired."""
        session = MockSession()
        # Set lock to expired time
        session["upload_lock"] = {"started_at": time.time() - UPLOAD_LOCK_TIMEOUT - 1}

        result = check_upload_in_progress(session)

        assert result is False
        # Lock should be cleared
        assert "upload_lock" not in session

    def test_clears_expired_lock(self):
        """Should clear expired lock from session."""
        session = MockSession()
        session["upload_lock"] = {"started_at": time.time() - UPLOAD_LOCK_TIMEOUT - 10}

        check_upload_in_progress(session)

        assert "upload_lock" not in session

    def test_returns_false_when_lock_is_empty(self):
        """Should return False when lock data is empty dict.

        An empty dict is falsy in Python, so it's treated as "no lock".
        """
        session = MockSession()
        session["upload_lock"] = {}  # Empty dict is falsy

        result = check_upload_in_progress(session)

        assert result is False

    def test_does_not_clear_valid_lock(self):
        """Should not clear a valid, non-expired lock."""
        session = MockSession()
        session["upload_lock"] = {"started_at": time.time()}

        check_upload_in_progress(session)

        assert "upload_lock" in session


# -----------------------------------------------------------------------------
# Tests for set_upload_in_progress()
# -----------------------------------------------------------------------------


class TestSetUploadInProgress:
    """Tests for set_upload_in_progress function."""

    def test_sets_lock_when_true(self):
        """Should set upload_lock with timestamp when in_progress=True."""
        session = MockSession()

        set_upload_in_progress(session, True)

        assert "upload_lock" in session
        assert "started_at" in session["upload_lock"]
        # Timestamp should be recent
        assert time.time() - session["upload_lock"]["started_at"] < 1

    def test_clears_lock_when_false(self):
        """Should remove upload_lock when in_progress=False."""
        session = MockSession()
        session["upload_lock"] = {"started_at": time.time()}

        set_upload_in_progress(session, False)

        assert "upload_lock" not in session

    def test_clear_on_empty_session(self):
        """Should handle clearing lock on session that has no lock."""
        session = MockSession()

        # Should not raise
        set_upload_in_progress(session, False)

        assert "upload_lock" not in session

    def test_overwrites_existing_lock(self):
        """Should overwrite existing lock with new timestamp."""
        session = MockSession()
        old_time = time.time() - 100
        session["upload_lock"] = {"started_at": old_time}

        set_upload_in_progress(session, True)

        assert session["upload_lock"]["started_at"] > old_time

    def test_stores_upload_token_fingerprint_when_token_is_supplied(self):
        """Should store a non-secret token fingerprint for cancel correlation."""
        session = MockSession()

        set_upload_in_progress(session, True, upload_token="signed-upload-token")

        lock = session["upload_lock"]
        assert lock["upload_lock_fingerprint"] == upload_token_fingerprint("signed-upload-token")
        assert "signed-upload-token" not in lock.values()


class TestUploadLockMatchesToken:
    """Tests for upload token/session-lock correlation."""

    def test_matches_current_token_fingerprint(self):
        session = MockSession()
        set_upload_in_progress(session, True, upload_token="current-token")

        assert upload_lock_matches_token(session, "current-token") is True

    def test_rejects_different_token(self):
        session = MockSession()
        set_upload_in_progress(session, True, upload_token="current-token")

        assert upload_lock_matches_token(session, "old-token") is False

    def test_rejects_lock_without_fingerprint(self):
        session = MockSession()
        set_upload_in_progress(session, True)

        assert upload_lock_matches_token(session, "current-token") is False

    def test_rejects_and_clears_expired_lock(self):
        session = MockSession()
        session["upload_lock"] = {
            "started_at": time.time() - UPLOAD_LOCK_TIMEOUT - 1,
            "upload_lock_fingerprint": upload_token_fingerprint("current-token"),
        }

        assert upload_lock_matches_token(session, "current-token") is False
        assert "upload_lock" not in session


# -----------------------------------------------------------------------------
# Tests for UPLOAD_LOCK_TIMEOUT constant
# -----------------------------------------------------------------------------


class TestUploadLockTimeout:
    """Tests for UPLOAD_LOCK_TIMEOUT constant."""

    def test_timeout_is_reasonable(self):
        """Timeout should be reasonable (between 10 seconds and 5 minutes)."""
        assert 10 <= UPLOAD_LOCK_TIMEOUT <= 300

    def test_timeout_is_integer(self):
        """Timeout should be an integer or compatible numeric type."""
        assert isinstance(UPLOAD_LOCK_TIMEOUT, (int, float))
