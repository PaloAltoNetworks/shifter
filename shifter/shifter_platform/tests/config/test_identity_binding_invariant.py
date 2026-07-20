"""Cross-provider verified-identity binding invariant (issue #1521).

Both ``ShifterOIDCBackend`` (Cognito/OIDC) and ``IdentityPlatformBackend``
(GCP Identity Platform) must converge on the same privilege invariant: a
login may bind or change bootstrap-admin flags only after strict
verification yields a non-empty ``issuer``, ``subject``, ``email``, and the
literal ``email_verified is True``; a bound account accepts only the same
``(issuer, subject)``. This suite drives each provider's real adapter
methods -- never mocking the binding service, bootstrap policy, or audit
facade -- parameterized so the invariant is proven identically on both
providers.

``ShifterOIDCBackend.verify_token``'s own issuer/audience/azp checks and
``IdentityPlatformBackend``'s domain-allowlist/MFA checks are provider-
specific and covered separately in ``tests/mission_control/test_oidc.py``
and ``tests/config/test_identity_platform.py``; here the (issuer, subject)
stashed on the OIDC backend stands in for a completed ``verify_token`` call,
matching the pattern already used by the existing bootstrap-admin/organizer-
authority tests that drive ``create_user`` / ``update_user`` directly.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import SuspiciousOperation
from django.test import override_settings

from config.identity_platform import IdentityPlatformAuthError, IdentityPlatformBackend
from config.oidc import ShifterOIDCBackend
from management.services import get_user_profile

User = get_user_model()

ISSUER_A = "https://issuer-a.example.test"
ISSUER_B = "https://issuer-b.example.test"

# The two fail-closed rejection types both providers raise for malformed,
# drifted, or colliding identity evidence (OIDC translates conflicts to
# SuspiciousOperation; Identity Platform to IdentityPlatformAuthError, whose
# email-verification subclass is also covered).
AUTH_REJECTIONS = (SuspiciousOperation, IdentityPlatformAuthError)


def _oidc_login(claims: dict) -> object:
    """Drive ShifterOIDCBackend's real hooks the way mozilla's get_or_create_user would.

    Simulates ``verify_token`` having already stashed the verified
    ``(iss, sub)`` -- the OIDC issuer/audience/azp checks in ``verify_token``
    itself are covered separately in ``test_oidc.py``.
    """
    backend = ShifterOIDCBackend()
    backend._verified_issuer = claims.get("iss")
    backend._verified_subject = claims.get("sub")

    if not backend.verify_claims(claims):
        raise SuspiciousOperation("OIDC claims verification failed")

    users = backend.filter_users_by_claims(claims)
    count = users.count()
    if count == 1:
        return backend.update_user(users.first(), claims)
    if count > 1:
        raise SuspiciousOperation("multiple users matched")
    return backend.create_user(claims)


def _identity_platform_login(claims: dict) -> object:
    backend = IdentityPlatformBackend()
    user = backend.authenticate(None, identity_claims=claims)
    if user is None:
        raise SuspiciousOperation("Identity Platform authentication failed")
    return user


PROVIDERS = pytest.mark.parametrize(
    "login",
    [pytest.param(_oidc_login, id="oidc"), pytest.param(_identity_platform_login, id="identity_platform")],
)


def _claims(*, iss=ISSUER_A, sub="sub-1", email="user@example.com", email_verified=True):
    return {"iss": iss, "sub": sub, "email": email, "email_verified": email_verified}


@pytest.fixture(autouse=True)
def _allow_example_domain(settings):
    """Both providers accept @example.com so the same claims fixtures work for
    OIDC (no domain check) and Identity Platform (domain-allowlisted)."""
    settings.IDENTITY_ALLOWED_EMAIL_DOMAIN = "example.com"


@pytest.mark.django_db
class TestVerifiedIdentityInvariantNegative:
    """No write and no elevation for any malformed/drifted verification evidence."""

    @PROVIDERS
    @pytest.mark.parametrize(
        "email_verified",
        [None, False, "false", 0, 1],
        ids=["missing", "false", "str-false", "int-0", "int-1"],
    )
    def test_rejects_non_literal_true_email_verified(self, login, email_verified):
        claims = _claims(email="new-user@example.com", email_verified=email_verified)
        if email_verified is None:
            del claims["email_verified"]

        with pytest.raises(AUTH_REJECTIONS):
            login(claims)

        assert not User.objects.filter(email="new-user@example.com").exists()

    @PROVIDERS
    def test_issuer_drift_same_subject_rejected(self, login):
        """A previously bound account accepts only the same issuer."""
        email = "drift@example.com"
        with override_settings(PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS=[email]):
            first = login(_claims(iss=ISSUER_A, sub="sub-drift", email=email))
        first.refresh_from_db()
        assert first.is_superuser is True

        claims = _claims(iss=ISSUER_B, sub="sub-drift", email=email)
        with (
            override_settings(PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS=[email]),
            pytest.raises(AUTH_REJECTIONS),
        ):
            login(claims)

        first.refresh_from_db()
        profile = get_user_profile(first)
        assert profile.issuer == ISSUER_A
        # Rejected before elevation runs: no de-elevation, no re-elevation.
        assert first.is_superuser is True
        assert User.objects.filter(email=email).count() == 1

    @PROVIDERS
    def test_subject_drift_same_email_rejected(self, login):
        """A previously bound account accepts only the same subject."""
        email = "subjectdrift@example.com"
        first = login(_claims(iss=ISSUER_A, sub="sub-orig", email=email))

        claims_2 = _claims(iss=ISSUER_A, sub="sub-new", email=email)
        with pytest.raises(AUTH_REJECTIONS):
            login(claims_2)

        assert User.objects.filter(email=email).count() == 1
        profile = get_user_profile(first)
        assert profile.cognito_sub == "sub-orig"

    @PROVIDERS
    def test_federated_same_email_different_subject_rejected(self, login):
        """A second, differently-provisioned federated identity presenting the
        same verified email must never claim the existing account."""
        email = "federated@example.com"
        login(_claims(iss=ISSUER_A, sub="sub-primary", email=email))

        claims_2 = _claims(iss=ISSUER_A, sub="sub-federated", email=email)
        with pytest.raises(AUTH_REJECTIONS):
            login(claims_2)

        assert User.objects.filter(email=email).count() == 1


@pytest.mark.django_db
class TestVerifiedIdentityInvariantPositive:
    @PROVIDERS
    def test_unbound_account_binds_once(self, login):
        email = "fresh@example.com"
        user = login(_claims(iss=ISSUER_A, sub="sub-fresh", email=email))

        profile = get_user_profile(user)
        assert profile.issuer == ISSUER_A
        assert profile.cognito_sub == "sub-fresh"

    @PROVIDERS
    def test_same_bound_tuple_is_idempotent(self, login):
        email = "repeat@example.com"
        first = login(_claims(iss=ISSUER_A, sub="sub-repeat", email=email))
        second = login(_claims(iss=ISSUER_A, sub="sub-repeat", email=email))

        assert first.pk == second.pk
        assert User.objects.filter(email=email).count() == 1

    @PROVIDERS
    def test_same_tuple_still_lets_bootstrap_list_grant(self, login):
        email = "grant@example.com"
        with override_settings(PLATFORM_BOOTSTRAP_STAFF_EMAILS=[email]):
            user = login(_claims(iss=ISSUER_A, sub="sub-grant", email=email))
        user.refresh_from_db()
        assert user.is_staff is True

    @PROVIDERS
    def test_same_tuple_still_lets_bootstrap_list_revoke(self, login):
        email = "revoke@example.com"
        with override_settings(PLATFORM_BOOTSTRAP_STAFF_EMAILS=[email]):
            user = login(_claims(iss=ISSUER_A, sub="sub-revoke", email=email))
        user.refresh_from_db()
        assert user.is_staff is True

        with override_settings(PLATFORM_BOOTSTRAP_STAFF_EMAILS=[]):
            login(_claims(iss=ISSUER_A, sub="sub-revoke", email=email))
        user.refresh_from_db()
        assert user.is_staff is False

    @PROVIDERS
    def test_legacy_subject_only_row_acquires_issuer(self, login):
        email = "legacy@example.com"
        user = User.objects.create_user(username=email, email=email)
        profile = get_user_profile(user)
        profile.cognito_sub = "sub-legacy"
        profile.issuer = ""
        profile.save(update_fields=["cognito_sub", "issuer"])

        result = login(_claims(iss=ISSUER_A, sub="sub-legacy", email=email))

        assert result.pk == user.pk
        profile.refresh_from_db()
        assert profile.issuer == ISSUER_A
        assert profile.cognito_sub == "sub-legacy"

    @PROVIDERS
    def test_federation_method_change_same_tuple_still_logs_in(self, login):
        """Upstream federation metadata (e.g. a sign-in-method switch) is not
        part of the identity key -- only (issuer, subject) is."""
        email = "federation-change@example.com"
        first = login(_claims(iss=ISSUER_A, sub="sub-fedchange", email=email))

        claims = _claims(iss=ISSUER_A, sub="sub-fedchange", email=email)
        claims["firebase.sign_in_provider"] = "google.com"
        second = login(claims)

        assert first.pk == second.pk
        assert User.objects.filter(email=email).count() == 1


@pytest.mark.django_db
class TestVerifiedIdentityInvariantAtomicity:
    """Resolution, first-login user creation, binding, elevation, and the strict
    audit are ONE atomic security mutation (issue #1521, codex review cycle 1):
    a binding conflict or a strict-audit failure rolls the whole login back, so
    no orphaned user or partially-elevated account survives a rejected login."""

    @PROVIDERS
    def test_binding_collision_on_new_login_rolls_back_created_user(self, login):
        # A subject already bound to an existing account under issuer A.
        login(_claims(iss=ISSUER_A, sub="sub-shared", email="owner@example.com"))
        assert User.objects.count() == 1

        # A brand-new login (unseen email -> email fallback would create a user)
        # presents the SAME subject under a different issuer. Resolution finds no
        # (issuer, subject) match, so a new user is created and the bind then hits
        # the unique-subject collision (IntegrityError -> BindingConflictError).
        # The freshly created user must roll back with the failed bind.
        claims_2 = _claims(iss=ISSUER_B, sub="sub-shared", email="intruder@example.com")
        with pytest.raises(AUTH_REJECTIONS):
            login(claims_2)

        assert not User.objects.filter(email="intruder@example.com").exists()
        assert User.objects.count() == 1

    @PROVIDERS
    def test_strict_audit_failure_rolls_back_user_and_elevation(self, login, monkeypatch):
        # Fault-inject a failing durable strict-audit write (an audit-infrastructure
        # failure, NOT a bypass) so the audit-failure branch of the atomic mutation
        # is exercised: user creation, issuer/subject binding, and staff/superuser
        # elevation must all roll back together.
        email = "audit-fail@example.com"
        target = "config.oidc.audit_log" if login is _oidc_login else "config.identity_platform.audit_log"

        def _boom(*_args, **_kwargs):
            raise RuntimeError("audit backend unavailable")

        monkeypatch.setattr(target, _boom)

        claims = _claims(iss=ISSUER_A, sub="sub-auditfail", email=email)
        with (
            override_settings(PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS=[email]),
            pytest.raises(RuntimeError),
        ):
            login(claims)

        assert not User.objects.filter(email=email).exists()
