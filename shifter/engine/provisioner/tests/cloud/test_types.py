"""Tests for provisioner cloud abstraction protocol definitions."""

from cloud.types import ConfigStore, DBAuth, EventBus, ObjectStorage, SecretsStore


class TestProtocolsAreRuntimeCheckable:
    """Verify all protocols are @runtime_checkable for isinstance() checks."""

    def test_event_bus_is_runtime_checkable(self):
        assert hasattr(EventBus, "_is_runtime_protocol")

    def test_config_store_is_runtime_checkable(self):
        assert hasattr(ConfigStore, "_is_runtime_protocol")

    def test_db_auth_is_runtime_checkable(self):
        assert hasattr(DBAuth, "_is_runtime_protocol")

    def test_object_storage_is_runtime_checkable(self):
        assert hasattr(ObjectStorage, "_is_runtime_protocol")

    def test_secrets_store_is_runtime_checkable(self):
        assert hasattr(SecretsStore, "_is_runtime_protocol")


class TestProtocolStructuralTyping:
    """Verify classes implementing the right methods satisfy isinstance() checks."""

    def test_event_bus_satisfied_by_conforming_class(self):
        class FakeBus:
            def publish(self, topic_id, message, attributes=None):
                pass

        assert isinstance(FakeBus(), EventBus)

    def test_config_store_satisfied_by_conforming_class(self):
        class FakeStore:
            def get_parameter(self, name):
                return ""

        assert isinstance(FakeStore(), ConfigStore)

    def test_db_auth_satisfied_by_conforming_class(self):
        class FakeAuth:
            def generate_auth_token(self, hostname, port, username):
                return ""

        assert isinstance(FakeAuth(), DBAuth)

    def test_object_storage_satisfied_by_conforming_class(self):
        class FakeStorage:
            def generate_presigned_download_url(self, bucket, key, expires_in=3600):
                return ""

            def object_exists(self, bucket, key):
                return True

            def delete_object(self, bucket, key):
                pass

        assert isinstance(FakeStorage(), ObjectStorage)

    def test_secrets_store_satisfied_by_conforming_class(self):
        class FakeSecrets:
            def get_secret(self, secret_id):
                return ""

        assert isinstance(FakeSecrets(), SecretsStore)

    def test_non_conforming_class_does_not_satisfy(self):
        class NotAnEventBus:
            pass

        assert not isinstance(NotAnEventBus(), EventBus)
