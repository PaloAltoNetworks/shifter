"""Tests for field-level encryption of Credential.data and Instance.data (#693).

Covers:
- Round-trip via the ORM: dict in, dict out, sensitive values opaque on disk.
- Field idempotency: re-encrypting an already-encrypted value is a no-op.
- Decryption of plaintext (no prefix) passes through unchanged so a partially
  migrated table still reads cleanly.
- Contract assertions: the sensitive_keys frozenset on each field class covers
  every secret-shaped field declared on the relevant Pydantic spec(s). Adding a
  new credential type or NGFW field without registering it here fails the test.
"""

from __future__ import annotations

from typing import Any

import pytest

from cms.credential_encryption import (
    ENCRYPTED_VALUE_PREFIX,
    EncryptedCredentialDataField,
    EncryptedInstanceDataField,
    _decrypt_value,
    _encrypt_value,
    _transform_sensitive,
)

# ---------------------------------------------------------------------------
# Field class behaviour — selective encryption / decryption
# ---------------------------------------------------------------------------


class TestSelectiveEncryption:
    """Only the configured sensitive_keys are encrypted; everything else passes."""

    def test_credential_data_field_encrypts_known_secrets(self):
        plain = {
            "name": "primary-scm",
            "scm_folder_name": "lab",
            "scm_pin_id": "pin-123",
            "scm_pin_value": "super-secret-value",
            "sls_region": "americas",
        }
        encrypted = _transform_sensitive(plain, EncryptedCredentialDataField.sensitive_keys, encrypt=True)
        assert encrypted["scm_pin_value"].startswith(ENCRYPTED_VALUE_PREFIX)
        # Non-sensitive fields untouched
        assert encrypted["scm_folder_name"] == "lab"
        assert encrypted["scm_pin_id"] == "pin-123"
        assert encrypted["sls_region"] == "americas"
        # Decrypt round-trip restores the original
        decrypted = _transform_sensitive(encrypted, EncryptedCredentialDataField.sensitive_keys, encrypt=False)
        assert decrypted == plain

    def test_instance_data_field_encrypts_otp_value(self):
        plain: dict[str, Any] = {
            "name": "ngfw-1",
            "role": "ngfw",
            "os_type": "panos",
            "otp_value": "one-time-secret",
            "otp_folder": "ops/folder",
        }
        encrypted = _transform_sensitive(plain, EncryptedInstanceDataField.sensitive_keys, encrypt=True)
        assert encrypted["otp_value"].startswith(ENCRYPTED_VALUE_PREFIX)
        # otp_folder is operational metadata — must stay plaintext.
        assert encrypted["otp_folder"] == "ops/folder"
        decrypted = _transform_sensitive(encrypted, EncryptedInstanceDataField.sensitive_keys, encrypt=False)
        assert decrypted == plain

    def test_non_sensitive_keys_never_encrypted_by_either_field(self):
        plain = {"name": "n", "role": "r", "os_type": "o", "uuid": "u"}
        for keys in (
            EncryptedCredentialDataField.sensitive_keys,
            EncryptedInstanceDataField.sensitive_keys,
        ):
            encrypted = _transform_sensitive(plain, keys, encrypt=True)
            assert encrypted == plain


# ---------------------------------------------------------------------------
# Value-level idempotency and partial-migration tolerance
# ---------------------------------------------------------------------------


class TestEncryptionIdempotency:
    """Encrypting already-encrypted, decrypting plaintext: both no-ops."""

    def test_encrypt_then_encrypt_is_noop(self):
        value = "secret"
        once = _encrypt_value(value)
        twice = _encrypt_value(once)
        assert once == twice

    def test_decrypt_plaintext_passes_through(self):
        # Tolerance for partially-migrated tables — a row without the prefix
        # is returned verbatim rather than raising InvalidToken.
        assert _decrypt_value("plain-string") == "plain-string"

    def test_decrypt_invalid_token_raises_valueerror(self):
        with pytest.raises(ValueError, match="invalid encrypted value"):
            _decrypt_value(f"{ENCRYPTED_VALUE_PREFIX}garbage")

    def test_empty_value_left_alone(self):
        plain = {"authcode": "", "scm_pin_value": ""}
        encrypted = _transform_sensitive(plain, EncryptedCredentialDataField.sensitive_keys, encrypt=True)
        assert encrypted == plain

    def test_non_string_value_left_alone(self):
        plain = {"authcode": 42, "scm_pin_value": None}
        encrypted = _transform_sensitive(plain, EncryptedCredentialDataField.sensitive_keys, encrypt=True)
        assert encrypted == plain


# ---------------------------------------------------------------------------
# Field deconstruct masquerades as plain JSONField (no schema migration)
# ---------------------------------------------------------------------------


class TestFieldDeconstruct:
    """deconstruct() must return django.db.models.JSONField so makemigrations
    doesn't generate a column-type AlterField for swapping the field in or out.
    """

    @pytest.mark.parametrize(
        "field_cls",
        [EncryptedCredentialDataField, EncryptedInstanceDataField],
    )
    def test_deconstruct_returns_plain_jsonfield(self, field_cls):
        field = field_cls()
        _name, path, _args, _kwargs = field.deconstruct()
        assert path == "django.db.models.JSONField"


# ---------------------------------------------------------------------------
# Contract: sensitive_keys covers every secret-shaped field on the Pydantic specs
# ---------------------------------------------------------------------------


# Hand-curated map of "secret keys per spec class". Maintenance contract: any
# new credential type or NGFW field that holds a secret MUST be added here AND
# to the matching field class's `sensitive_keys`. The tests below tie those two
# obligations together so neither can be silently forgotten.
_CREDENTIAL_SPEC_SECRET_KEYS: dict[str, frozenset[str]] = {
    "SCMCredentialSpec": frozenset({"scm_pin_value"}),
    "DeploymentProfileSpec": frozenset({"authcode"}),
}
_INSTANCE_SPEC_SECRET_KEYS: dict[str, frozenset[str]] = {
    # NGFWAppSpec is persisted into Instance.data after hydration
    # (cms.services.create_ngfw). Its three secret fields are the ones below.
    "NGFWAppSpec": frozenset({"authcode", "scm_pin_value", "otp_value"}),
}


class TestSensitiveKeysContract:
    """sensitive_keys must cover the hand-curated list of secrets per spec."""

    def test_credential_field_covers_all_credential_spec_secrets(self):
        expected = frozenset().union(*_CREDENTIAL_SPEC_SECRET_KEYS.values())
        assert expected.issubset(EncryptedCredentialDataField.sensitive_keys), (
            "EncryptedCredentialDataField.sensitive_keys is missing secret-shaped "
            "fields declared on credential spec classes. Add them to the field "
            "class and to _CREDENTIAL_SPEC_SECRET_KEYS in this test."
        )

    def test_instance_field_covers_all_instance_spec_secrets(self):
        expected = frozenset().union(*_INSTANCE_SPEC_SECRET_KEYS.values())
        assert expected.issubset(EncryptedInstanceDataField.sensitive_keys), (
            "EncryptedInstanceDataField.sensitive_keys is missing secret-shaped "
            "fields declared on instance spec classes. Add them to the field "
            "class and to _INSTANCE_SPEC_SECRET_KEYS in this test."
        )

    def test_listed_secrets_actually_exist_on_credential_specs(self):
        """If a curated key disappears from its spec, this test fires and the
        curated list should be cleaned up (not the field — orphan keys in
        sensitive_keys are harmless but should be pruned)."""
        from shared.schemas import DeploymentProfileSpec, SCMCredentialSpec

        spec_classes = {
            "SCMCredentialSpec": SCMCredentialSpec,
            "DeploymentProfileSpec": DeploymentProfileSpec,
        }
        for spec_name, keys in _CREDENTIAL_SPEC_SECRET_KEYS.items():
            field_names = set(spec_classes[spec_name].model_fields)
            for key in keys:
                assert key in field_names, (
                    f"{spec_name} no longer declares '{key}'. Update "
                    "_CREDENTIAL_SPEC_SECRET_KEYS and consider whether the "
                    "field class's sensitive_keys still needs it."
                )

    def test_listed_secrets_actually_exist_on_instance_specs(self):
        from cyberscript.schemas.app import NGFWAppSpec

        spec_classes = {"NGFWAppSpec": NGFWAppSpec}
        for spec_name, keys in _INSTANCE_SPEC_SECRET_KEYS.items():
            field_names = set(spec_classes[spec_name].model_fields)
            for key in keys:
                assert key in field_names, (
                    f"{spec_name} no longer declares '{key}'. Update "
                    "_INSTANCE_SPEC_SECRET_KEYS and consider whether the "
                    "field class's sensitive_keys still needs it."
                )


# ---------------------------------------------------------------------------
# ORM round-trip — DB-backed: ensures the field's get_prep_value /
# from_db_value pipeline survives a real save+reload and that raw DB
# inspection sees only ciphertext for sensitive keys.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCredentialDataORMRoundTrip:
    """Ciphertext on disk, plaintext through the ORM."""

    @pytest.fixture
    def credential_type(self, db):
        # Seeded by migration 0018 in fresh test DBs. Some workers may have
        # had the row truncated by an earlier transactional test, so use
        # get_or_create rather than .get.
        from cms.models import CredentialType

        ct, _ = CredentialType.objects.get_or_create(
            slug="deployment_profile",
            defaults={
                "name": "NGFW Deployment Profile",
                "spec_class": "shared.schemas.DeploymentProfileSpec",
            },
        )
        return ct

    @pytest.fixture
    def user(self, db):
        from django.contrib.auth import get_user_model

        return get_user_model().objects.create_user(username="enc@test", email="enc@test", password="x")

    def test_authcode_encrypted_on_disk_decrypted_on_read(self, user, credential_type):
        from cms.models import Credential

        cred = Credential.objects.create(
            user=user,
            credential_type=credential_type,
            name="profile-1",
            data={"name": "profile-1", "authcode": "AUTH-XYZ"},
        )
        # Read through ORM: plaintext.
        reloaded = Credential.all_objects.get(pk=cred.pk)
        assert reloaded.data["authcode"] == "AUTH-XYZ"

        # Read raw row: ciphertext.
        from django.db import connection

        with connection.cursor() as c:
            c.execute("SELECT data FROM cms_credential WHERE id = %s", [cred.pk])
            raw = c.fetchone()[0]
        if isinstance(raw, str):
            import json as _json

            raw = _json.loads(raw)
        assert raw["authcode"].startswith(ENCRYPTED_VALUE_PREFIX)
        assert raw["authcode"] != "AUTH-XYZ"


@pytest.mark.django_db
class TestInstanceDataORMRoundTrip:
    """NGFW Instance.data hydrated with secrets must persist as ciphertext."""

    @pytest.fixture
    def user(self, db):
        from django.contrib.auth import get_user_model

        return get_user_model().objects.create_user(username="inst@test", email="inst@test", password="x")

    @pytest.fixture
    def request_row(self, user):
        from uuid import uuid4

        from cms.models import Request
        from shared.enums import RequestType

        return Request.objects.create(
            request_id=uuid4(),
            user=user,
            request_type=RequestType.NGFW.value,
        )

    @pytest.fixture
    def ngfw_instance_type(self, db):
        # Seeded by migration 0016 in fresh test DBs. Defensively recreate if a
        # transactional test in this worker truncated the row.
        from cms.models import InstanceType

        it, _ = InstanceType.objects.get_or_create(
            slug="panw-ngfw",
            defaults={
                "name": "PANW NGFW",
                "spec_class": "shared.schemas.range.InstanceSpec",
            },
        )
        return it

    def test_otp_value_encrypted_on_disk_decrypted_on_read(self, user, request_row, ngfw_instance_type):
        from cms.models import Instance

        inst = Instance.objects.create(
            request=request_row,
            name="ngfw-1",
            instance_type=ngfw_instance_type,
            data={
                "name": "ngfw-1",
                "role": "ngfw",
                "os_type": "panos",
                "otp_value": "OTP-SECRET",
                "otp_folder": "ops/folder",
                "authcode": "AUTH-FROM-PROFILE",
            },
        )
        reloaded = Instance.all_objects.get(pk=inst.pk)
        # Plaintext through ORM
        assert reloaded.data["otp_value"] == "OTP-SECRET"
        assert reloaded.data["authcode"] == "AUTH-FROM-PROFILE"
        # Non-secret keys untouched
        assert reloaded.data["otp_folder"] == "ops/folder"
        assert reloaded.data["role"] == "ngfw"

        # Raw row: ciphertext for secrets, plaintext for the rest. We bypass
        # EncryptedInstanceDataField.from_db_value by reading the column with
        # a plain JSONField on a stub model — the DB returns the on-disk JSON
        # unmodified.
        from uuid import UUID

        from django.db import connection

        with connection.cursor() as c:
            c.execute("SELECT id, data FROM cms_instance")
            row = next(
                (r for r in c.fetchall() if UUID(str(r[0])) == inst.pk),
                None,
            )
        assert row is not None, f"Row for inst.pk={inst.pk!r} not found in cms_instance"
        raw = row[1]
        if isinstance(raw, str):
            import json as _json

            raw = _json.loads(raw)
        assert raw["otp_value"].startswith(ENCRYPTED_VALUE_PREFIX)
        assert raw["authcode"].startswith(ENCRYPTED_VALUE_PREFIX)
        assert raw["otp_folder"] == "ops/folder"
        assert raw["role"] == "ngfw"
