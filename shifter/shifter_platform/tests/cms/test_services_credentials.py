"""CMS service interface tests.

Tests service-level behavior only:
- Expected behavior / return values
- Logging (debug and error levels)
- Exception handling
- Input validation (service's responsibility)

Does NOT re-test model behavior (filtering, field validation, etc).
"""

import logging
from unittest.mock import Mock, patch

import pytest
from django.contrib.auth import get_user_model

from cms import services
from cms.models import OperatingSystem
from mission_control.models import AgentConfig

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(username="test@example.com", email="test@example.com")


@pytest.fixture
def agent(user, db):
    """Create an agent for testing."""
    os = OperatingSystem.objects.get(slug="windows")
    return AgentConfig.objects.create(
        user=user,
        name="Test Agent",
        os=os,
        s3_key="agents/test/agent.msi",
        original_filename="agent.msi",
        file_size_bytes=1000,
        sha256_hash="abc123",
    )


@pytest.mark.django_db
class TestListCredentials:
    """Tests for list_credentials() service function.

    Tests SERVICE behavior with mocked model layer:
    - Calls model correctly
    - Returns what model returns
    - Logs all errors from downstream
    - Validates input
    - Propagates errors
    """

    # -------------------------------------------------------------------------
    # Service calls model correctly
    # -------------------------------------------------------------------------

    def test_calls_active_for_user_with_user(self, user):
        """Service calls Credential.active_for_user with the user."""
        from cms.models import Credential

        with patch.object(Credential, "active_for_user", return_value=[]) as mock_active:
            services.list_credentials(user)
            mock_active.assert_called_once_with(user)

    # -------------------------------------------------------------------------
    # Service returns what model returns
    # -------------------------------------------------------------------------

    def test_returns_empty_list_when_model_returns_empty(self, user):
        """Service returns empty list when model returns empty queryset."""
        from cms.models import Credential

        with patch.object(Credential, "active_for_user", return_value=[]):
            result = services.list_credentials(user)
            assert result == []

    def test_returns_one_credential_when_model_returns_one(self, user):
        """Service returns one credential when model returns one."""
        from cms.models import Credential

        mock_cred = Mock(spec=Credential, id=42)
        mock_cred.configure_mock(name="Mock Credential")
        with patch.object(Credential, "active_for_user", return_value=[mock_cred]):
            result = services.list_credentials(user)
            assert len(result) == 1
            assert result[0].id == 42

    def test_returns_all_credentials_when_model_returns_multiple(self, user):
        """Service returns all credentials model returns."""
        from cms.models import Credential

        mock_creds = [Mock(spec=Credential, id=i) for i in range(5)]
        with patch.object(Credential, "active_for_user", return_value=mock_creds):
            result = services.list_credentials(user)
            assert len(result) == 5
            assert [c.id for c in result] == [0, 1, 2, 3, 4]

    def test_returns_both_credential_types(self, user):
        """Service returns both SCM and deployment profile credentials."""
        from cms.models import Credential

        mock_scm = Mock(spec=Credential, id=1, credential_type="scm")
        mock_dp = Mock(spec=Credential, id=2, credential_type="deployment_profile")
        with patch.object(Credential, "active_for_user", return_value=[mock_scm, mock_dp]):
            result = services.list_credentials(user)
            assert len(result) == 2
            types = {c.credential_type for c in result}
            assert types == {"scm", "deployment_profile"}

    # -------------------------------------------------------------------------
    # Logging - DEBUG on success
    # -------------------------------------------------------------------------

    def test_logs_debug_on_entry(self, user, caplog):
        """Service logs debug on entry with user info."""
        from cms.models import Credential

        with (
            patch.object(Credential, "active_for_user", return_value=[]),
            caplog.at_level(logging.DEBUG, logger="cms.services"),
        ):
            services.list_credentials(user)
        assert str(user.id) in caplog.text

    def test_logs_debug_on_success_with_count(self, user, caplog):
        """Service logs debug on success with count."""
        from cms.models import Credential

        mock_creds = [Mock(spec=Credential) for _ in range(3)]
        with (
            patch.object(Credential, "active_for_user", return_value=mock_creds),
            caplog.at_level(logging.DEBUG, logger="cms.services"),
        ):
            services.list_credentials(user)
        assert "3" in caplog.text

    # -------------------------------------------------------------------------
    # Logging - ERROR on failures
    # -------------------------------------------------------------------------

    def test_logs_error_on_downstream_exception(self, user, caplog):
        """Service logs error when model raises exception."""
        from cms.models import Credential

        with (
            patch.object(Credential, "active_for_user", side_effect=RuntimeError("DB connection failed")),
            caplog.at_level(logging.ERROR, logger="cms.services"),
            pytest.raises(RuntimeError),
        ):
            services.list_credentials(user)
        assert "error" in caplog.text.lower() or "exception" in caplog.text.lower()

    # -------------------------------------------------------------------------
    # Error propagation
    # -------------------------------------------------------------------------

    def test_propagates_model_exception(self, user):
        """Service propagates exceptions from model."""
        from cms.models import Credential

        with (
            patch.object(Credential, "active_for_user", side_effect=ValueError("Model error")),
            pytest.raises(ValueError, match="Model error"),
        ):
            services.list_credentials(user)

    # -------------------------------------------------------------------------
    # Response validation - model returns garbage
    # -------------------------------------------------------------------------

    def test_raises_on_model_returns_none(self, user):
        """Service raises TypeError if model returns None instead of list."""
        from cms.models import Credential

        with patch.object(Credential, "active_for_user", return_value=None), pytest.raises(TypeError):
            services.list_credentials(user)

    def test_raises_on_model_returns_string(self, user):
        """Service raises TypeError if model returns string instead of list."""
        from cms.models import Credential

        with patch.object(Credential, "active_for_user", return_value="not a list"), pytest.raises(TypeError):
            services.list_credentials(user)

    def test_raises_on_model_returns_list_of_wrong_type(self, user):
        """Service raises TypeError if model returns list of wrong type."""
        from cms.models import Credential

        with (
            patch.object(Credential, "active_for_user", return_value=[{"id": 1}, {"id": 2}]),
            pytest.raises(TypeError),
        ):
            services.list_credentials(user)

    def test_logs_error_on_invalid_model_response(self, user, caplog):
        """Service logs error when model returns invalid response."""
        from cms.models import Credential

        with (
            patch.object(Credential, "active_for_user", return_value=None),
            caplog.at_level(logging.ERROR, logger="cms.services"),
            pytest.raises(TypeError),
        ):
            services.list_credentials(user)
        assert "error" in caplog.text.lower() or "invalid" in caplog.text.lower()

    # -------------------------------------------------------------------------
    # Return type guarantee
    # -------------------------------------------------------------------------

    def test_returns_list_class_not_queryset(self, user):
        """Service returns list class, not QuerySet."""
        from cms.models import Credential

        mock_qs = Mock()
        mock_qs.__iter__ = Mock(return_value=iter([Mock(spec=Credential)]))
        with patch.object(Credential, "active_for_user", return_value=mock_qs):
            result = services.list_credentials(user)
            assert type(result) is list

    def test_returns_list_class_not_tuple(self, user):
        """Service returns list, not tuple even if model returns tuple."""
        from cms.models import Credential

        mock_cred = Mock(spec=Credential)
        with patch.object(Credential, "active_for_user", return_value=(mock_cred,)):
            result = services.list_credentials(user)
            assert type(result) is list

    # -------------------------------------------------------------------------
    # Input validation - user parameter
    # -------------------------------------------------------------------------

    def test_requires_user_argument(self):
        """Service raises TypeError if user not provided."""
        with pytest.raises(TypeError):
            services.list_credentials()

    def test_raises_on_none_user(self):
        """Service raises error if user is None."""
        with pytest.raises((TypeError, ValueError)):
            services.list_credentials(None)

    def test_raises_on_invalid_user_type(self):
        """Service raises error if user is wrong type."""
        with pytest.raises((TypeError, AttributeError)):
            services.list_credentials("not-a-user")

    def test_raises_on_unsaved_user(self, db):
        """Service raises error if user has no ID (unsaved)."""
        unsaved_user = User(username="unsaved", email="unsaved@test.com")
        assert unsaved_user.id is None
        with pytest.raises((TypeError, ValueError)):
            services.list_credentials(unsaved_user)

    def test_logs_error_on_invalid_user(self, caplog):
        """Service logs error when given invalid user."""
        with caplog.at_level(logging.ERROR, logger="cms.services"), pytest.raises((TypeError, ValueError)):
            services.list_credentials(None)
        assert "error" in caplog.text.lower() or "invalid" in caplog.text.lower() or "none" in caplog.text.lower()


@pytest.mark.django_db
class TestGetCredential:
    """Tests for get_credential() service function.

    Tests SERVICE behavior with mocked model layer:
    - Calls model correctly
    - Returns what model returns
    - Logs all errors from downstream
    - Validates input
    - Propagates errors
    - Raises CMSError for business logic failures (not found, ownership, deleted)
    """

    # -------------------------------------------------------------------------
    # Service calls model correctly
    # -------------------------------------------------------------------------

    def test_calls_objects_get_with_credential_id(self, user):
        """Service queries Credential by id."""
        from cms.models import Credential

        mock_cred = Mock(spec=Credential, id=42, user=user, deleted_at=None)
        with patch.object(Credential.objects, "get", return_value=mock_cred) as mock_get:
            services.get_credential(user, 42)
            mock_get.assert_called_once_with(id=42)

    # -------------------------------------------------------------------------
    # Service returns what model returns
    # -------------------------------------------------------------------------

    def test_returns_credential_when_found_and_owned(self, user):
        """Service returns credential when it exists and belongs to user."""
        from cms.models import Credential

        mock_cred = Mock(spec=Credential, id=42, user=user, deleted_at=None)
        with patch.object(Credential.objects, "get", return_value=mock_cred):
            result = services.get_credential(user, 42)
            assert result.id == 42

    def test_returns_credential_with_correct_attributes(self, user):
        """Service returns credential with all attributes intact."""
        from cms.models import Credential

        mock_cred = Mock(spec=Credential, id=42, user=user, deleted_at=None, credential_type="scm")
        mock_cred.configure_mock(name="Test Credential")
        with patch.object(Credential.objects, "get", return_value=mock_cred):
            result = services.get_credential(user, 42)
            assert result.name == "Test Credential"
            assert result.credential_type == "scm"

    # -------------------------------------------------------------------------
    # Logging - DEBUG on success
    # -------------------------------------------------------------------------

    def test_logs_debug_on_entry(self, user, caplog):
        """Service logs debug on entry with user_id and credential_id."""
        from cms.models import Credential

        mock_cred = Mock(spec=Credential, id=42, user=user, deleted_at=None)
        with (
            patch.object(Credential.objects, "get", return_value=mock_cred),
            caplog.at_level(logging.DEBUG, logger="cms.services"),
        ):
            services.get_credential(user, 42)
        assert str(user.id) in caplog.text
        assert "42" in caplog.text

    def test_logs_debug_on_success(self, user, caplog):
        """Service logs debug on successful retrieval."""
        from cms.models import Credential

        mock_cred = Mock(spec=Credential, id=42, user=user, deleted_at=None)
        with (
            patch.object(Credential.objects, "get", return_value=mock_cred),
            caplog.at_level(logging.DEBUG, logger="cms.services"),
        ):
            services.get_credential(user, 42)
        assert "42" in caplog.text

    # -------------------------------------------------------------------------
    # Logging - ERROR on failures
    # -------------------------------------------------------------------------

    def test_logs_error_when_credential_not_found(self, user, caplog):
        """Service logs error when credential doesn't exist."""
        from cms.exceptions import CMSError
        from cms.models import Credential

        with (
            patch.object(Credential.objects, "get", side_effect=Credential.DoesNotExist),
            caplog.at_level(logging.ERROR, logger="cms.services"),
            pytest.raises(CMSError),
        ):
            services.get_credential(user, 999)
        assert "error" in caplog.text.lower() or "not found" in caplog.text.lower()

    def test_logs_error_when_credential_owned_by_other_user(self, user, caplog):
        """Service logs error when credential belongs to different user."""
        from cms.exceptions import CMSError
        from cms.models import Credential

        other_user = Mock(id=999)
        mock_cred = Mock(spec=Credential, id=42, user=other_user, deleted_at=None)
        with (
            patch.object(Credential.objects, "get", return_value=mock_cred),
            caplog.at_level(logging.ERROR, logger="cms.services"),
            pytest.raises(CMSError),
        ):
            services.get_credential(user, 42)
        assert "error" in caplog.text.lower() or "denied" in caplog.text.lower() or "owner" in caplog.text.lower()

    def test_logs_error_when_credential_is_deleted(self, user, caplog):
        """Service logs error when credential is soft-deleted."""
        from django.utils import timezone

        from cms.exceptions import CMSError
        from cms.models import Credential

        mock_cred = Mock(spec=Credential, id=42, user=user, deleted_at=timezone.now())
        with (
            patch.object(Credential.objects, "get", return_value=mock_cred),
            caplog.at_level(logging.ERROR, logger="cms.services"),
            pytest.raises(CMSError),
        ):
            services.get_credential(user, 42)
        assert "error" in caplog.text.lower() or "deleted" in caplog.text.lower()

    def test_logs_error_on_database_failure(self, user, caplog):
        """Service logs error when database raises exception."""
        from cms.models import Credential

        with (
            patch.object(Credential.objects, "get", side_effect=RuntimeError("DB connection failed")),
            caplog.at_level(logging.ERROR, logger="cms.services"),
            pytest.raises(RuntimeError),
        ):
            services.get_credential(user, 42)
        assert "error" in caplog.text.lower() or "exception" in caplog.text.lower()

    # -------------------------------------------------------------------------
    # Error handling - CMSError for business logic failures
    # -------------------------------------------------------------------------

    def test_raises_cms_error_when_credential_not_found(self, user):
        """Service raises CMSError when credential doesn't exist."""
        from cms.exceptions import CMSError
        from cms.models import Credential

        with (
            patch.object(Credential.objects, "get", side_effect=Credential.DoesNotExist),
            pytest.raises(CMSError),
        ):
            services.get_credential(user, 999)

    def test_raises_cms_error_when_credential_owned_by_other_user(self, user):
        """Service raises CMSError when credential belongs to different user."""
        from cms.exceptions import CMSError
        from cms.models import Credential

        other_user = Mock(id=999)
        mock_cred = Mock(spec=Credential, id=42, user=other_user, deleted_at=None)
        with (
            patch.object(Credential.objects, "get", return_value=mock_cred),
            pytest.raises(CMSError),
        ):
            services.get_credential(user, 42)

    def test_raises_cms_error_when_credential_is_deleted(self, user):
        """Service raises CMSError when credential is soft-deleted."""
        from django.utils import timezone

        from cms.exceptions import CMSError
        from cms.models import Credential

        mock_cred = Mock(spec=Credential, id=42, user=user, deleted_at=timezone.now())
        with (
            patch.object(Credential.objects, "get", return_value=mock_cred),
            pytest.raises(CMSError),
        ):
            services.get_credential(user, 42)

    def test_cms_error_has_descriptive_message_for_not_found(self, user):
        """CMSError message indicates credential not found."""
        from cms.exceptions import CMSError
        from cms.models import Credential

        with (
            patch.object(Credential.objects, "get", side_effect=Credential.DoesNotExist),
            pytest.raises(CMSError, match=r"not found|does not exist"),
        ):
            services.get_credential(user, 999)

    # -------------------------------------------------------------------------
    # Error propagation - non-business errors
    # -------------------------------------------------------------------------

    def test_propagates_database_exception(self, user):
        """Service propagates unexpected database errors."""
        from cms.models import Credential

        with (
            patch.object(Credential.objects, "get", side_effect=Exception("DB connection failed")),
            pytest.raises(Exception, match="DB connection failed"),
        ):
            services.get_credential(user, 42)

    # -------------------------------------------------------------------------
    # Input validation - user parameter
    # -------------------------------------------------------------------------

    def test_requires_user_argument(self):
        """Service raises TypeError if user not provided."""
        with pytest.raises(TypeError):
            services.get_credential(credential_id=42)

    def test_raises_on_none_user(self):
        """Service raises error if user is None."""
        with pytest.raises((TypeError, ValueError)):
            services.get_credential(None, 42)

    def test_raises_on_invalid_user_type(self):
        """Service raises error if user is wrong type."""
        with pytest.raises((TypeError, AttributeError)):
            services.get_credential("not-a-user", 42)

    def test_raises_on_unsaved_user(self, db):
        """Service raises error if user has no ID (unsaved)."""
        unsaved_user = User(username="unsaved", email="unsaved@test.com")
        assert unsaved_user.id is None
        with pytest.raises((TypeError, ValueError)):
            services.get_credential(unsaved_user, 42)

    def test_logs_error_on_invalid_user(self, caplog):
        """Service logs error when given invalid user."""
        with caplog.at_level(logging.ERROR, logger="cms.services"), pytest.raises((TypeError, ValueError)):
            services.get_credential(None, 42)
        assert "error" in caplog.text.lower() or "invalid" in caplog.text.lower() or "none" in caplog.text.lower()

    # -------------------------------------------------------------------------
    # Input validation - credential_id parameter
    # -------------------------------------------------------------------------

    def test_requires_credential_id_argument(self, user):
        """Service raises TypeError if credential_id not provided."""
        with pytest.raises(TypeError):
            services.get_credential(user)

    def test_raises_on_none_credential_id(self, user):
        """Service raises error if credential_id is None."""
        with pytest.raises((TypeError, ValueError)):
            services.get_credential(user, None)

    def test_raises_on_invalid_credential_id_type(self, user):
        """Service raises error if credential_id is wrong type."""
        with pytest.raises((TypeError, ValueError)):
            services.get_credential(user, "not-an-id")

    def test_raises_on_negative_credential_id(self, user):
        """Service raises error if credential_id is negative."""
        with pytest.raises((TypeError, ValueError)):
            services.get_credential(user, -1)

    def test_logs_error_on_invalid_credential_id(self, user, caplog):
        """Service logs error when given invalid credential_id."""
        with caplog.at_level(logging.ERROR, logger="cms.services"), pytest.raises((TypeError, ValueError)):
            services.get_credential(user, None)
        assert "error" in caplog.text.lower() or "invalid" in caplog.text.lower() or "none" in caplog.text.lower()

    # -------------------------------------------------------------------------
    # Response validation - model returns garbage
    # -------------------------------------------------------------------------

    def test_raises_on_model_returns_none(self, user):
        """Service raises TypeError if model returns None instead of credential."""
        from cms.models import Credential

        with patch.object(Credential.objects, "get", return_value=None), pytest.raises(TypeError):
            services.get_credential(user, 42)

    def test_raises_on_model_returns_wrong_type(self, user):
        """Service raises TypeError if model returns wrong type."""
        from cms.models import Credential

        with patch.object(Credential.objects, "get", return_value="not a credential"), pytest.raises(TypeError):
            services.get_credential(user, 42)

    def test_logs_error_on_invalid_model_response(self, user, caplog):
        """Service logs error when model returns invalid response."""
        from cms.models import Credential

        with (
            patch.object(Credential.objects, "get", return_value=None),
            caplog.at_level(logging.ERROR, logger="cms.services"),
            pytest.raises(TypeError),
        ):
            services.get_credential(user, 42)
        assert "error" in caplog.text.lower() or "invalid" in caplog.text.lower()


@pytest.mark.django_db
class TestCreateCredential:
    """Tests for create_credential() service function.

    Tests SERVICE behavior:
    - Creates correct credential type (SCM or deployment profile)
    - Validates required fields based on type
    - Logs activity on creation
    - Propagates errors
    """

    # -------------------------------------------------------------------------
    # Create SCM credential
    # -------------------------------------------------------------------------

    def test_create_scm_credential_succeeds(self, user):
        """Service creates SCM credential with valid data."""
        from cms.models import Credential

        with patch.object(Credential, "save") as mock_save:
            result = services.create_credential(
                user,
                credential_type="scm",
                name="My SCM",
                scm_folder_name="test-folder",
                scm_pin_id="pin123",
                scm_pin_value="secret",
                sls_region="americas",
            )
            mock_save.assert_called_once()
            assert result.credential_type == "scm"

    def test_create_scm_credential_returns_credential(self, user):
        """Service returns the created credential."""
        from cms.models import Credential

        with patch.object(Credential, "save"):
            result = services.create_credential(
                user,
                credential_type="scm",
                name="My SCM",
                scm_folder_name="test-folder",
                scm_pin_id="pin123",
                scm_pin_value="secret",
                sls_region="americas",
            )
            assert isinstance(result, Credential)
            assert result.user == user

    # -------------------------------------------------------------------------
    # Create deployment profile
    # -------------------------------------------------------------------------

    def test_create_deployment_profile_succeeds(self, user):
        """Service creates deployment profile with valid data."""
        from cms.models import Credential

        with patch.object(Credential, "save") as mock_save:
            result = services.create_credential(
                user,
                credential_type="deployment_profile",
                name="My DP",
                authcode="D1234567",
            )
            mock_save.assert_called_once()
            assert result.credential_type == "deployment_profile"

    def test_create_deployment_profile_returns_credential(self, user):
        """Service returns the created deployment profile."""
        from cms.models import Credential

        with patch.object(Credential, "save"):
            result = services.create_credential(
                user,
                credential_type="deployment_profile",
                name="My DP",
                authcode="D1234567",
            )
            assert isinstance(result, Credential)
            assert result.authcode == "D1234567"

    # -------------------------------------------------------------------------
    # Input validation - credential_type
    # -------------------------------------------------------------------------

    def test_raises_on_invalid_credential_type(self, user):
        """Service raises error for invalid credential type."""
        with pytest.raises((ValueError, TypeError)):
            services.create_credential(
                user,
                credential_type="invalid_type",
                name="Test",
            )

    def test_raises_on_none_credential_type(self, user):
        """Service raises error if credential_type is None."""
        with pytest.raises((ValueError, TypeError)):
            services.create_credential(
                user,
                credential_type=None,
                name="Test",
            )

    # -------------------------------------------------------------------------
    # Input validation - user parameter
    # -------------------------------------------------------------------------

    def test_requires_user_argument(self):
        """Service raises TypeError if user not provided."""
        with pytest.raises(TypeError):
            services.create_credential(
                credential_type="scm",
                name="Test",
            )

    def test_raises_on_none_user(self):
        """Service raises error if user is None."""
        with pytest.raises((TypeError, ValueError)):
            services.create_credential(
                None,
                credential_type="scm",
                name="Test",
            )

    def test_raises_on_unsaved_user(self, db):
        """Service raises error if user has no ID (unsaved)."""
        unsaved_user = User(username="unsaved", email="unsaved@test.com")
        with pytest.raises((TypeError, ValueError)):
            services.create_credential(
                unsaved_user,
                credential_type="scm",
                name="Test",
            )

    # -------------------------------------------------------------------------
    # Logging
    # -------------------------------------------------------------------------

    def test_logs_debug_on_entry(self, user, caplog):
        """Service logs debug on entry."""
        from cms.models import Credential

        with (
            patch.object(Credential, "save"),
            caplog.at_level(logging.DEBUG, logger="cms.services"),
        ):
            services.create_credential(
                user,
                credential_type="deployment_profile",
                name="Test DP",
                authcode="D1234567",
            )
        assert str(user.id) in caplog.text

    def test_logs_debug_on_success(self, user, caplog):
        """Service logs debug on successful creation."""
        from cms.models import Credential

        with (
            patch.object(Credential, "save"),
            caplog.at_level(logging.DEBUG, logger="cms.services"),
        ):
            services.create_credential(
                user,
                credential_type="deployment_profile",
                name="Test DP",
                authcode="D1234567",
            )
        assert "deployment_profile" in caplog.text.lower() or "created" in caplog.text.lower()

    def test_logs_error_on_validation_failure(self, user, caplog):
        """Service logs error when validation fails."""
        with caplog.at_level(logging.ERROR, logger="cms.services"), pytest.raises((ValueError, TypeError)):
            services.create_credential(
                user,
                credential_type="invalid",
                name="Test",
            )
        assert "error" in caplog.text.lower() or "invalid" in caplog.text.lower()


@pytest.mark.django_db
class TestDeleteCredential:
    """Tests for delete_credential() service function.

    Tests SERVICE behavior:
    - Validates ownership before deletion
    - Performs soft delete
    - Logs activity
    - Propagates errors
    """

    # -------------------------------------------------------------------------
    # Service validates ownership and deletes
    # -------------------------------------------------------------------------

    def test_gets_credential_to_verify_ownership(self, user):
        """Service calls get_credential to verify ownership."""
        from cms.models import Credential

        mock_cred = Mock(spec=Credential, id=42, user=user, deleted_at=None)
        with (
            patch.object(services, "get_credential", return_value=mock_cred) as mock_get,
            patch.object(mock_cred, "save"),
        ):
            services.delete_credential(user, 42)
            mock_get.assert_called_once_with(user, 42)

    def test_soft_deletes_credential(self, user):
        """Service performs soft delete by setting deleted_at."""
        from cms.models import Credential

        mock_cred = Mock(spec=Credential, id=42, user=user, deleted_at=None)
        with (
            patch.object(services, "get_credential", return_value=mock_cred),
            patch.object(mock_cred, "save") as mock_save,
        ):
            services.delete_credential(user, 42)
            assert mock_cred.deleted_at is not None
            mock_save.assert_called_once()

    def test_returns_none_on_success(self, user):
        """Service returns None on successful deletion."""
        from cms.models import Credential

        mock_cred = Mock(spec=Credential, id=42, user=user, deleted_at=None)
        with (
            patch.object(services, "get_credential", return_value=mock_cred),
            patch.object(mock_cred, "save"),
        ):
            result = services.delete_credential(user, 42)
            assert result is None

    # -------------------------------------------------------------------------
    # Logging
    # -------------------------------------------------------------------------

    def test_logs_debug_on_entry(self, user, caplog):
        """Service logs debug on entry with user_id and credential_id."""
        from cms.models import Credential

        mock_cred = Mock(spec=Credential, id=42, user=user, deleted_at=None)
        with (
            patch.object(services, "get_credential", return_value=mock_cred),
            patch.object(mock_cred, "save"),
            caplog.at_level(logging.DEBUG, logger="cms.services"),
        ):
            services.delete_credential(user, 42)
        assert str(user.id) in caplog.text
        assert "42" in caplog.text

    def test_logs_debug_on_success(self, user, caplog):
        """Service logs debug on successful deletion."""
        from cms.models import Credential

        mock_cred = Mock(spec=Credential, id=42, user=user, deleted_at=None)
        with (
            patch.object(services, "get_credential", return_value=mock_cred),
            patch.object(mock_cred, "save"),
            caplog.at_level(logging.DEBUG, logger="cms.services"),
        ):
            services.delete_credential(user, 42)
        assert "42" in caplog.text

    def test_logs_error_when_credential_not_found(self, user, caplog):
        """Service logs error when get_credential raises CMSError."""
        from cms.exceptions import CMSError

        with (
            patch.object(services, "get_credential", side_effect=CMSError("not found")),
            caplog.at_level(logging.ERROR, logger="cms.services"),
            pytest.raises(CMSError),
        ):
            services.delete_credential(user, 999)
        assert "error" in caplog.text.lower() or "not found" in caplog.text.lower()

    # -------------------------------------------------------------------------
    # Error handling
    # -------------------------------------------------------------------------

    def test_raises_cms_error_when_credential_not_found(self, user):
        """Service raises CMSError when credential doesn't exist."""
        from cms.exceptions import CMSError

        with patch.object(services, "get_credential", side_effect=CMSError("not found")), pytest.raises(CMSError):
            services.delete_credential(user, 999)

    def test_raises_cms_error_when_not_owner(self, user):
        """Service raises CMSError when user doesn't own credential (via get_credential)."""
        from cms.exceptions import CMSError

        with (
            patch.object(services, "get_credential", side_effect=CMSError("access denied")),
            pytest.raises(CMSError),
        ):
            services.delete_credential(user, 42)

    def test_propagates_unexpected_exception(self, user):
        """Service propagates unexpected exceptions."""
        from cms.models import Credential

        mock_cred = Mock(spec=Credential, id=42, user=user, deleted_at=None)
        with (
            patch.object(services, "get_credential", return_value=mock_cred),
            patch.object(mock_cred, "save", side_effect=Exception("DB connection failed")),
            pytest.raises(Exception, match="DB connection failed"),
        ):
            services.delete_credential(user, 42)

    # -------------------------------------------------------------------------
    # Input validation
    # -------------------------------------------------------------------------

    def test_requires_user_argument(self):
        """Service raises TypeError if user not provided."""
        with pytest.raises(TypeError):
            services.delete_credential(credential_id=42)

    def test_raises_on_none_user(self):
        """Service raises error if user is None."""
        with pytest.raises((TypeError, ValueError)):
            services.delete_credential(None, 42)

    def test_raises_on_unsaved_user(self, db):
        """Service raises error if user has no ID (unsaved)."""
        unsaved_user = User(username="unsaved", email="unsaved@test.com")
        with pytest.raises((TypeError, ValueError)):
            services.delete_credential(unsaved_user, 42)

    def test_raises_on_none_credential_id(self, user):
        """Service raises error if credential_id is None."""
        with pytest.raises((TypeError, ValueError)):
            services.delete_credential(user, None)

    def test_raises_on_invalid_credential_id_type(self, user):
        """Service raises error if credential_id is wrong type."""
        with pytest.raises((TypeError, ValueError)):
            services.delete_credential(user, "not-an-id")

    def test_raises_on_negative_credential_id(self, user):
        """Service raises error if credential_id is negative."""
        with pytest.raises((TypeError, ValueError)):
            services.delete_credential(user, -1)

    def test_logs_error_on_invalid_credential_id(self, user, caplog):
        """Service logs error when given invalid credential_id."""
        with caplog.at_level(logging.ERROR, logger="cms.services"), pytest.raises((TypeError, ValueError)):
            services.delete_credential(user, None)
        assert "error" in caplog.text.lower() or "invalid" in caplog.text.lower() or "none" in caplog.text.lower()
