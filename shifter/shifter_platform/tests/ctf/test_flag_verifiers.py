"""Unit tests for per-flag-type verifier helpers (issue #779 burndown)."""

from types import SimpleNamespace

from ctf.services.challenge import _verify_regex_flag, _verify_static_flag


def _flag(**kw):
    base = {"id": 1, "case_sensitive": True, "flag_hash": "", "flag_type": "regex"}
    base.update(kw)
    return SimpleNamespace(**base)


class TestVerifyRegexFlag:
    def test_matches_pattern(self):
        assert _verify_regex_flag(_flag(flag_hash=r"flag\{.*\}"), "flag{abc}") is True

    def test_no_match(self):
        assert _verify_regex_flag(_flag(flag_hash=r"flag\{.*\}"), "nope") is False

    def test_case_insensitive(self):
        assert _verify_regex_flag(_flag(flag_hash=r"flag", case_sensitive=False), "FLAG") is True

    def test_invalid_regex_returns_false(self):
        # An unbalanced group is an invalid pattern; the helper must swallow the
        # re.error and return False rather than propagate.
        assert _verify_regex_flag(_flag(flag_hash=r"flag(["), "flag") is False


class TestVerifyStaticFlag:
    def test_mismatch_returns_false(self):
        # An arbitrary stored hash will not match the submission; exercises the
        # static (hashed) comparison path without depending on the hash scheme.
        assert _verify_static_flag(_flag(flag_hash="0" * 64, case_sensitive=True), "xyz") is False

    def test_case_insensitive_path(self):
        assert _verify_static_flag(_flag(flag_hash="0" * 64, case_sensitive=False), "XYZ") is False
