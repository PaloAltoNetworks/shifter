"""Tests for Django admin configuration."""

from engine.admin import UserNGFWAdmin


class TestUserNGFWAdmin:
    """Tests for UserNGFWAdmin configuration."""

    def test_raw_id_fields_no_credential_fks(self):
        """UserNGFWAdmin should not reference credential FK fields.

        UserNGFW no longer has credential FKs - credentials are managed by CMS
        and passed as hydrated config values at provisioning time.
        """
        assert "deployment_profile" not in UserNGFWAdmin.raw_id_fields
        assert "scm_credential" not in UserNGFWAdmin.raw_id_fields
