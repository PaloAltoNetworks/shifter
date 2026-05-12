"""Tests for the sensitive-env classifier (#1185)."""

from __future__ import annotations

import pytest

from engine.ecs import _GCP_PROVISIONER_ENV_KEYS
from shared.cloud.sensitive_env import is_sensitive, split_env

# Expected sensitive names in the provisioner env contract. Adding a
# new sensitive key to `_GCP_PROVISIONER_ENV_KEYS` must come with a
# matching addition here, OR be classed by the suffix rules (in which
# case the test below verifies the classifier still puts it on the
# sensitive side). Codex review #1180 cycle 2 finding 4.
EXPECTED_SENSITIVE = frozenset(
    {
        "DB_PASSWORD",
        "FIELD_ENCRYPTION_KEY",
        "DC_DOMAIN_PASSWORD",
    }
)

# Derived from the authoritative env contract minus EXPECTED_SENSITIVE.
# Both tuples cover every entry in `_GCP_PROVISIONER_ENV_KEYS`; the
# `test_full_contract_partitioned_with_no_unclassified_names` test
# enforces that invariant.
SENSITIVE = tuple(sorted(EXPECTED_SENSITIVE))
NON_SENSITIVE = tuple(name for name in _GCP_PROVISIONER_ENV_KEYS if name not in EXPECTED_SENSITIVE)


class TestProvisionerEnvContract:
    """Backstop against drift between the provisioner env contract and
    the sensitive classifier (codex review #1180 cycle 2 finding 4)."""

    def test_full_contract_partitioned_with_no_unclassified_names(self) -> None:
        """Every name in `_GCP_PROVISIONER_ENV_KEYS` lands in exactly
        one of the two pinned halves; nothing falls through."""
        contract = set(_GCP_PROVISIONER_ENV_KEYS)
        assert contract == EXPECTED_SENSITIVE | set(NON_SENSITIVE)

    def test_expected_sensitive_matches_classifier(self) -> None:
        """The pinned EXPECTED_SENSITIVE set is the ground truth. The
        classifier must agree on every name in the contract: names in
        EXPECTED_SENSITIVE return True; the rest return False."""
        for name in _GCP_PROVISIONER_ENV_KEYS:
            expected = name in EXPECTED_SENSITIVE
            assert is_sensitive(name) is expected, (
                f"{name}: classifier says is_sensitive={is_sensitive(name)} but EXPECTED_SENSITIVE says {expected}"
            )


class TestIsSensitive:
    """Classification of individual env var names."""

    @pytest.mark.parametrize("name", SENSITIVE)
    def test_known_sensitive_names_are_classed_sensitive(self, name: str) -> None:
        assert is_sensitive(name) is True

    @pytest.mark.parametrize("name", NON_SENSITIVE)
    def test_known_non_sensitive_names_are_classed_plain(self, name: str) -> None:
        assert is_sensitive(name) is False

    def test_generic_suffix_rules(self) -> None:
        """Suffix rules catch new variants without requiring an allowlist entry."""
        assert is_sensitive("ROOT_PASSPHRASE") is True
        assert is_sensitive("MY_API_TOKEN") is True
        assert is_sensitive("ROUTE_CREDENTIAL") is True
        assert is_sensitive("SVC_CREDENTIALS") is True
        assert is_sensitive("JWT_SECRET") is True
        assert is_sensitive("RSA_PRIVATE_KEY") is True

    def test_pointer_suffixes_win_over_sensitive_suffixes(self) -> None:
        """An identifier ending in a pointer suffix is never sensitive."""
        # `_SECRET_ID` ends in `_ID`, which is a pointer suffix. The
        # identifier itself is a Secret Manager id, not the secret.
        assert is_sensitive("MY_DB_SECRET_ID") is False
        assert is_sensitive("CRED_BUCKET") is False
        # Even an explicit allowlist member with a pointer suffix would
        # be unreachable; the parametrization above pins the real cases.

    def test_safe_names_with_no_matching_rules_default_to_plain(self) -> None:
        """Names with no suffix or allowlist match default to non-sensitive."""
        assert is_sensitive("DB_USER") is False
        assert is_sensitive("ENVIRONMENT") is False


class TestSplitEnv:
    """Partitioning the full env dict."""

    def test_routes_each_key_to_the_correct_half(self) -> None:
        env = {
            "DB_PASSWORD": "secret-value",
            "FIELD_ENCRYPTION_KEY": "key-value",
            "DC_DOMAIN_PASSWORD": "domain-pass",
            "DB_HOST": "rds.example.com",
            "DB_USER": "shifter",
            "GDC_ACCESS_SECRET_ID": "projects/x/secrets/y",
            "CLOUD_REGION": "us-east-2",
        }

        sensitive, plain = split_env(env)

        assert set(sensitive.keys()) == {
            "DB_PASSWORD",
            "FIELD_ENCRYPTION_KEY",
            "DC_DOMAIN_PASSWORD",
        }
        assert set(plain.keys()) == {
            "DB_HOST",
            "DB_USER",
            "GDC_ACCESS_SECRET_ID",
            "CLOUD_REGION",
        }
        # Values pass through unchanged on both halves.
        assert sensitive["DB_PASSWORD"] == "secret-value"
        assert plain["DB_HOST"] == "rds.example.com"

    def test_empty_input_returns_empty_halves(self) -> None:
        sensitive, plain = split_env({})
        assert sensitive == {}
        assert plain == {}

    def test_all_sensitive_input_returns_empty_plain(self) -> None:
        env = {"DB_PASSWORD": "p", "FIELD_ENCRYPTION_KEY": "k"}
        sensitive, plain = split_env(env)
        assert sensitive == env
        assert plain == {}

    def test_all_plain_input_returns_empty_sensitive(self) -> None:
        env = {"DB_HOST": "h", "CLOUD_REGION": "r"}
        sensitive, plain = split_env(env)
        assert sensitive == {}
        assert plain == env
