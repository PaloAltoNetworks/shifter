"""Unit tests for per-flag-type verifier helpers (issue #779 burndown)."""

from types import SimpleNamespace

import pytest

from ctf.services.challenge import _verify_regex_flag, _verify_static_flag


def _flag(**kw):
    base = {"id": 1, "case_sensitive": True, "value": "", "flag_type": "regex"}
    base.update(kw)
    return SimpleNamespace(**base)


class TestVerifyRegexFlag:
    def test_matches_pattern(self):
        assert _verify_regex_flag(_flag(value=r"flag\{.*\}"), "flag{abc}") is True

    def test_no_match(self):
        assert _verify_regex_flag(_flag(value=r"flag\{.*\}"), "nope") is False

    def test_case_insensitive(self):
        assert _verify_regex_flag(_flag(value=r"flag", case_sensitive=False), "FLAG") is True

    def test_invalid_regex_returns_false(self):
        # An unbalanced group is an invalid pattern; the helper must swallow the
        # re.error and return False rather than propagate.
        assert _verify_regex_flag(_flag(value=r"flag(["), "flag") is False


class TestVerifyStaticFlag:
    """Static flags are stored as their normalized inner value; a submission is
    accepted as ``FLAG{v}`` (any case of "flag"), ``{v}``, or bare ``v``."""

    @pytest.mark.parametrize(
        "submission",
        ["FLAG{s3cret}", "flag{s3cret}", "Flag{s3cret}", "{s3cret}", "s3cret", "  FLAG{s3cret}\n"],
    )
    def test_every_wrapper_form_matches(self, submission):
        assert _verify_static_flag(_flag(value="s3cret", flag_type="static"), submission) is True

    @pytest.mark.parametrize("submission", ["FLAG{other}", "s3cre", "FLAG{s3cret", "FLAG{{s3cret}}", "", "FLAG{}"])
    def test_wrong_or_malformed_submissions_do_not_match(self, submission):
        assert _verify_static_flag(_flag(value="s3cret", flag_type="static"), submission) is False

    def test_case_sensitivity_is_honored_for_the_inner_value(self):
        assert _verify_static_flag(_flag(value="S3cret", flag_type="static"), "FLAG{s3cret}") is False
        flag = _flag(value="S3cret", flag_type="static", case_sensitive=False)
        assert _verify_static_flag(flag, "flag{s3CRET}") is True

    def test_inner_braces_are_part_of_the_value(self):
        assert _verify_static_flag(_flag(value="a{b}c", flag_type="static"), "FLAG{a{b}c}") is True
