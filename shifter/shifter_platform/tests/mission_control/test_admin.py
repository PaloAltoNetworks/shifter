"""Tests for Django admin configuration."""

from cms.admin import NGFWAdmin


class TestNGFWAdmin:
    """Tests for NGFWAdmin configuration."""

    def test_raw_id_fields_no_credential_fks(self):
        """NGFWAdmin should not reference credential FK fields.

        NGFW no longer has credential FKs - credentials are managed by CMS
        and passed as hydrated config values at provisioning time.
        """
        assert "deployment_profile" not in NGFWAdmin.raw_id_fields
        assert "scm_credential" not in NGFWAdmin.raw_id_fields
