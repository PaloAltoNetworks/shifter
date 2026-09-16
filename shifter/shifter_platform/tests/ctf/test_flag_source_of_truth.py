"""Flag source-of-truth consolidation (#532).

`CTFFlag` is the sole persisted source of flag truth. These tests pin the
post-consolidation contract: a single plaintext ``flag`` normalizes to exactly
one static ``CTFFlag``, ``verify_flag`` has no legacy ``challenge.flag_hash``
fallback, and ambiguous write payloads are rejected.
"""

from __future__ import annotations

import logging

import pytest

from ctf.enums import ChallengeCategory, ChallengeDifficulty
from ctf.exceptions import CTFValidationError
from ctf.services import create_challenge, update_challenge, verify_flag

pytestmark = pytest.mark.django_db


def _base_challenge_data(**overrides):
    data = {
        "name": "SoT Challenge",
        "description": "source of truth",
        "category": ChallengeCategory.WEB.value,
        "points": 100,
        "difficulty": ChallengeDifficulty.EASY.value,
    }
    data.update(overrides)
    return data


class TestSingleFlagNormalization:
    """A plaintext ``flag`` is an input alias for one static ``CTFFlag``."""

    def test_create_with_plaintext_flag_creates_one_static_ctfflag(self, ctf_event_draft):
        challenge = create_challenge(
            event_id=ctf_event_draft.pk,
            challenge_data=_base_challenge_data(flag="FLAG{canonical}"),
            actor_id=ctf_event_draft.created_by_id,
        )
        flags = list(challenge.flags.all())
        assert len(flags) == 1
        assert flags[0].flag_type == "static"
        assert verify_flag(challenge, "FLAG{canonical}") is True
        assert verify_flag(challenge, "FLAG{nope}") is False

    def test_create_rejects_flag_and_flags_together(self, ctf_event_draft):
        data = _base_challenge_data(flag="FLAG{a}", flags=[{"flag": "FLAG{b}", "flag_type": "static"}])
        with pytest.raises(CTFValidationError):
            create_challenge(
                event_id=ctf_event_draft.pk,
                challenge_data=data,
                actor_id=ctf_event_draft.created_by_id,
            )

    def test_create_rejects_explicitly_empty_flags(self, ctf_event_draft):
        data = _base_challenge_data(flags=[])
        with pytest.raises(CTFValidationError):
            create_challenge(
                event_id=ctf_event_draft.pk,
                challenge_data=data,
                actor_id=ctf_event_draft.created_by_id,
            )

    def test_update_with_plaintext_flag_replaces_flag_set(self, ctf_event_draft):
        challenge = create_challenge(
            event_id=ctf_event_draft.pk,
            challenge_data=_base_challenge_data(flag="FLAG{old}"),
            actor_id=ctf_event_draft.created_by_id,
        )
        update_challenge(
            challenge_id=challenge.pk,
            challenge_data={"flag": "FLAG{new}"},
            actor_id=ctf_event_draft.created_by_id,
        )
        challenge.refresh_from_db()
        assert challenge.flags.count() == 1
        assert verify_flag(challenge, "FLAG{new}") is True
        assert verify_flag(challenge, "FLAG{old}") is False


class TestNoLegacyFallback:
    """Removing the last ``CTFFlag`` makes a challenge unverifiable; there is no
    fallback to a legacy challenge-level hash."""

    def test_verify_flag_without_ctfflag_rows_is_false_and_logs(self, ctf_event_draft, caplog):
        challenge = create_challenge(
            event_id=ctf_event_draft.pk,
            challenge_data=_base_challenge_data(flag="FLAG{gone}"),
            actor_id=ctf_event_draft.created_by_id,
        )
        challenge.flags.all().delete()

        # App loggers set propagate=False, so attach caplog's handler directly to
        # the service logger to capture the loud error.
        svc_logger = logging.getLogger("ctf.services.challenge")
        svc_logger.addHandler(caplog.handler)
        try:
            with caplog.at_level(logging.ERROR, logger="ctf.services.challenge"):
                assert verify_flag(challenge, "FLAG{gone}") is False
        finally:
            svc_logger.removeHandler(caplog.handler)
        assert "every submission will be rejected" in caplog.text
