"""Unit tests for StrataConfig model.

Tests cover:
- Expected behavior: creation, defaults, queries, soft delete
- Failure modes: missing required fields, validation errors
- Edge cases: special characters in PINs, empty results
"""

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.utils import timezone

from mission_control.models import StrataConfig

User = get_user_model()


@pytest.mark.django_db
class TestStrataConfigCreation:
    """Tests for StrataConfig creation and field requirements."""

    @pytest.fixture
    def user(self):
        return User.objects.create_user(username="test@example.com", email="test@example.com")

    def test_create_with_required_fields(self, user):
        """StrataConfig can be created with all required fields."""
        config = StrataConfig.objects.create(
            user=user,
            name="My SCM Config",
            scm_folder_name="Edwards-Lab",
            scm_pin_id="pin-id-12345",
            scm_pin_value="pin-value-secret-67890",
        )
        assert config.pk is not None
        assert config.user == user
        assert config.name == "My SCM Config"
        assert config.scm_folder_name == "Edwards-Lab"
        assert config.scm_pin_id == "pin-id-12345"
        assert config.scm_pin_value == "pin-value-secret-67890"

    def test_missing_user_raises_integrity_error(self):
        """Creating StrataConfig without user raises IntegrityError."""
        with pytest.raises(IntegrityError):
            StrataConfig.objects.create(
                name="No User",
                scm_folder_name="Test",
                scm_pin_id="pin123",
                scm_pin_value="secret",
            )

    def test_missing_name_raises_integrity_error(self, user):
        """Creating StrataConfig without name raises IntegrityError."""
        with pytest.raises(IntegrityError):
            StrataConfig.objects.create(
                user=user,
                name=None,  # Explicitly None to trigger NOT NULL
                scm_folder_name="Test",
                scm_pin_id="pin123",
                scm_pin_value="secret",
            )

    def test_missing_scm_folder_name_raises_integrity_error(self, user):
        """Creating StrataConfig without scm_folder_name raises IntegrityError."""
        with pytest.raises(IntegrityError):
            StrataConfig.objects.create(
                user=user,
                name="Test",
                scm_folder_name=None,
                scm_pin_id="pin123",
                scm_pin_value="secret",
            )

    def test_missing_scm_pin_id_raises_integrity_error(self, user):
        """Creating StrataConfig without scm_pin_id raises IntegrityError."""
        with pytest.raises(IntegrityError):
            StrataConfig.objects.create(
                user=user,
                name="Test",
                scm_folder_name="Test",
                scm_pin_id=None,
                scm_pin_value="secret",
            )

    def test_missing_scm_pin_value_raises_integrity_error(self, user):
        """Creating StrataConfig without scm_pin_value raises IntegrityError."""
        with pytest.raises(IntegrityError):
            StrataConfig.objects.create(
                user=user,
                name="Test",
                scm_folder_name="Test",
                scm_pin_id="pin123",
                scm_pin_value=None,
            )


@pytest.mark.django_db
class TestStrataConfigDefaults:
    """Tests for default field values."""

    @pytest.fixture
    def user(self):
        return User.objects.create_user(username="test@example.com", email="test@example.com")

    def test_deleted_at_defaults_to_none(self, user):
        """deleted_at defaults to None (not soft-deleted)."""
        config = StrataConfig.objects.create(
            user=user,
            name="Test",
            scm_folder_name="Folder",
            scm_pin_id="pin123",
            scm_pin_value="secret",
        )
        assert config.deleted_at is None

    def test_created_at_auto_set(self, user):
        """created_at is automatically set on creation."""
        config = StrataConfig.objects.create(
            user=user,
            name="Test",
            scm_folder_name="Folder",
            scm_pin_id="pin123",
            scm_pin_value="secret",
        )
        assert config.created_at is not None
        # Should be recent (within last minute)
        assert (timezone.now() - config.created_at).total_seconds() < 60


@pytest.mark.django_db
class TestStrataConfigSoftDelete:
    """Tests for soft delete functionality."""

    @pytest.fixture
    def user(self):
        return User.objects.create_user(username="test@example.com", email="test@example.com")

    def test_is_deleted_false_by_default(self, user):
        """is_deleted returns False when deleted_at is None."""
        config = StrataConfig.objects.create(
            user=user,
            name="Test",
            scm_folder_name="Folder",
            scm_pin_id="pin123",
            scm_pin_value="secret",
        )
        assert config.is_deleted is False

    def test_is_deleted_true_when_deleted_at_set(self, user):
        """is_deleted returns True when deleted_at is set."""
        config = StrataConfig.objects.create(
            user=user,
            name="Test",
            scm_folder_name="Folder",
            scm_pin_id="pin123",
            scm_pin_value="secret",
        )
        config.deleted_at = timezone.now()
        config.save()
        assert config.is_deleted is True

    def test_soft_deleted_record_still_exists_in_db(self, user):
        """Soft-deleted config still exists in database."""
        config = StrataConfig.objects.create(
            user=user,
            name="Test",
            scm_folder_name="Folder",
            scm_pin_id="pin123",
            scm_pin_value="secret",
        )
        config.deleted_at = timezone.now()
        config.save()

        # Still exists in database
        assert StrataConfig.objects.filter(pk=config.pk).exists()


@pytest.mark.django_db
class TestStrataConfigActiveForUser:
    """Tests for active_for_user class method."""

    @pytest.fixture
    def user(self):
        return User.objects.create_user(username="test@example.com", email="test@example.com")

    @pytest.fixture
    def other_user(self):
        return User.objects.create_user(username="other@example.com", email="other@example.com")

    def test_active_for_user_returns_user_configs(self, user):
        """active_for_user returns configs for the specified user."""
        config = StrataConfig.objects.create(
            user=user,
            name="My Config",
            scm_folder_name="Folder",
            scm_pin_id="pin123",
            scm_pin_value="secret",
        )
        result = list(StrataConfig.active_for_user(user))
        assert len(result) == 1
        assert result[0] == config

    def test_active_for_user_excludes_other_users(self, user, other_user):
        """active_for_user excludes other users' configs."""
        StrataConfig.objects.create(
            user=user,
            name="My Config",
            scm_folder_name="Folder",
            scm_pin_id="pin123",
            scm_pin_value="secret",
        )
        StrataConfig.objects.create(
            user=other_user,
            name="Other Config",
            scm_folder_name="OtherFolder",
            scm_pin_id="other-pin",
            scm_pin_value="other-secret",
        )

        result = list(StrataConfig.active_for_user(user))
        assert len(result) == 1
        assert result[0].name == "My Config"

    def test_active_for_user_excludes_soft_deleted(self, user):
        """active_for_user excludes soft-deleted configs."""
        active = StrataConfig.objects.create(
            user=user,
            name="Active",
            scm_folder_name="Folder",
            scm_pin_id="pin123",
            scm_pin_value="secret",
        )
        StrataConfig.objects.create(
            user=user,
            name="Deleted",
            scm_folder_name="Folder2",
            scm_pin_id="pin456",
            scm_pin_value="secret2",
            deleted_at=timezone.now(),
        )

        result = list(StrataConfig.active_for_user(user))
        assert len(result) == 1
        assert result[0] == active

    def test_active_for_user_returns_empty_for_no_configs(self, user):
        """active_for_user returns empty queryset when user has no configs."""
        result = list(StrataConfig.active_for_user(user))
        assert result == []

    def test_active_for_user_returns_multiple_configs(self, user):
        """active_for_user returns all active configs for user."""
        config1 = StrataConfig.objects.create(
            user=user,
            name="Config 1",
            scm_folder_name="Folder1",
            scm_pin_id="pin1",
            scm_pin_value="secret1",
        )
        config2 = StrataConfig.objects.create(
            user=user,
            name="Config 2",
            scm_folder_name="Folder2",
            scm_pin_id="pin2",
            scm_pin_value="secret2",
        )

        result = list(StrataConfig.active_for_user(user))
        assert len(result) == 2
        # Ordered by -created_at, so newest first
        assert result[0] == config2
        assert result[1] == config1


@pytest.mark.django_db
class TestStrataConfigInitCfgContext:
    """Tests for get_init_cfg_context method.

    This method is critical - it provides the context for rendering
    the init-cfg.txt template that bootstraps the NGFW. Wrong values
    here mean the NGFW fails to register with SCM.
    """

    @pytest.fixture
    def user(self):
        return User.objects.create_user(username="test@example.com", email="test@example.com")

    def test_get_init_cfg_context_returns_expected_keys(self, user):
        """get_init_cfg_context returns dict with correct keys."""
        config = StrataConfig.objects.create(
            user=user,
            name="Test",
            scm_folder_name="MyFolder",
            scm_pin_id="pin-123",
            scm_pin_value="secret-456",
        )
        context = config.get_init_cfg_context()

        assert "pin_id" in context
        assert "pin_value" in context
        assert "folder_name" in context

    def test_get_init_cfg_context_returns_correct_values(self, user):
        """get_init_cfg_context returns the actual config values."""
        config = StrataConfig.objects.create(
            user=user,
            name="Test",
            scm_folder_name="Edwards-Personal-Lab",
            scm_pin_id="abc123-pin-id",
            scm_pin_value="xyz789-pin-value",
        )
        context = config.get_init_cfg_context()

        assert context["folder_name"] == "Edwards-Personal-Lab"
        assert context["pin_id"] == "abc123-pin-id"
        assert context["pin_value"] == "xyz789-pin-value"

    def test_get_init_cfg_context_preserves_special_characters(self, user):
        """Special characters in PIN values are preserved.

        SCM PIN values may contain special characters. These must be
        passed through to init-cfg.txt exactly as stored.
        """
        config = StrataConfig.objects.create(
            user=user,
            name="Test",
            scm_folder_name="Folder-With_Special.Chars",
            scm_pin_id="pin+id/with=special",
            scm_pin_value="secret!@#$%^&*()",
        )
        context = config.get_init_cfg_context()

        assert context["folder_name"] == "Folder-With_Special.Chars"
        assert context["pin_id"] == "pin+id/with=special"
        assert context["pin_value"] == "secret!@#$%^&*()"


@pytest.mark.django_db
class TestStrataConfigStringRepresentation:
    """Tests for __str__ method."""

    @pytest.fixture
    def user(self):
        return User.objects.create_user(username="test@example.com", email="test@example.com")

    def test_str_includes_name_and_folder(self, user):
        """__str__ returns name and folder for identification."""
        config = StrataConfig.objects.create(
            user=user,
            name="My SCM Config",
            scm_folder_name="Edwards-Lab",
            scm_pin_id="pin123",
            scm_pin_value="secret",
        )
        str_repr = str(config)
        assert "My SCM Config" in str_repr
        assert "Edwards-Lab" in str_repr


@pytest.mark.django_db
class TestStrataConfigEdgeCases:
    """Tests for edge cases and boundary conditions."""

    @pytest.fixture
    def user(self):
        return User.objects.create_user(username="test@example.com", email="test@example.com")

    def test_empty_string_fields_are_invalid(self, user):
        """Empty strings for required fields should fail validation.

        While Django allows empty strings by default, our model should
        require meaningful values for PIN fields.
        """
        # This tests that we've properly configured the model
        # to not allow blank=True on required fields
        config = StrataConfig(
            user=user,
            name="Test",
            scm_folder_name="",  # Empty
            scm_pin_id="pin123",
            scm_pin_value="secret",
        )
        # full_clean() runs field validators
        with pytest.raises(ValidationError):
            config.full_clean()

    def test_long_folder_name_stored_correctly(self, user):
        """Long folder names are stored without truncation."""
        long_name = "A" * 200  # Well within 255 limit
        config = StrataConfig.objects.create(
            user=user,
            name="Test",
            scm_folder_name=long_name,
            scm_pin_id="pin123",
            scm_pin_value="secret",
        )
        config.refresh_from_db()
        assert config.scm_folder_name == long_name
        assert len(config.scm_folder_name) == 200

    def test_unicode_in_name_allowed(self, user):
        """Unicode characters in name field are allowed."""
        config = StrataConfig.objects.create(
            user=user,
            name="Palo Alto Config",
            scm_folder_name="Folder",
            scm_pin_id="pin123",
            scm_pin_value="secret",
        )
        assert config.name == "Palo Alto Config"
