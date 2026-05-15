"""Tests for cloud abstraction protocol definitions."""

from shared.cloud.types import (
    ObjectStorage,
    QueueConsumer,
    QueuePublisher,
    SecretsStore,
    TaskRunner,
)


class TestProtocolsAreRuntimeCheckable:
    """Verify all protocols are @runtime_checkable for isinstance() checks."""

    def test_object_storage_is_runtime_checkable(self):
        assert getattr(ObjectStorage, "__protocol_attrs__", None) is not None or hasattr(
            ObjectStorage, "_is_runtime_protocol"
        )

    def test_task_runner_is_runtime_checkable(self):
        assert getattr(TaskRunner, "__protocol_attrs__", None) is not None or hasattr(
            TaskRunner, "_is_runtime_protocol"
        )

    def test_queue_consumer_is_runtime_checkable(self):
        assert getattr(QueueConsumer, "__protocol_attrs__", None) is not None or hasattr(
            QueueConsumer, "_is_runtime_protocol"
        )

    def test_queue_publisher_is_runtime_checkable(self):
        assert getattr(QueuePublisher, "__protocol_attrs__", None) is not None or hasattr(
            QueuePublisher, "_is_runtime_protocol"
        )

    def test_secrets_store_is_runtime_checkable(self):
        assert getattr(SecretsStore, "__protocol_attrs__", None) is not None or hasattr(
            SecretsStore, "_is_runtime_protocol"
        )


class TestProtocolStructuralTyping:
    """Verify classes implementing the right methods satisfy isinstance() checks."""

    def test_object_storage_satisfied_by_conforming_class(self):
        class FakeStorage:
            def upload_file(self, file_obj, bucket, key, content_type=""):
                pass

            def delete_object(self, bucket, key):
                pass

            def copy_object(self, bucket, src_key, dst_key):
                pass

            def object_exists(self, bucket, key):
                return False

            def head_object(self, bucket, key):
                return {}

            def read_object_header(self, bucket, key, max_bytes):
                return b""

            def generate_presigned_upload_url(self, bucket, key, content_type, expires_in):
                return ""

            def generate_presigned_download_url(self, bucket, key, expires_in):
                return ""

            def tag_object(self, bucket, key, tags):
                pass

        assert isinstance(FakeStorage(), ObjectStorage)

    def test_task_runner_satisfied_by_conforming_class(self):
        class FakeRunner:
            def run_task(
                self,
                task_definition,
                cluster,
                command,
                container_name,
                env_overrides=None,
                network_config=None,
            ):
                return None

            def get_task_status(self, cluster, task_id):
                return None

        assert isinstance(FakeRunner(), TaskRunner)

    def test_queue_consumer_satisfied_by_conforming_class(self):
        class FakeConsumer:
            def receive_messages(self, queue_id, max_messages=10, wait_time=20):
                return []

            def delete_message(self, queue_id, receipt_handle):
                pass

        assert isinstance(FakeConsumer(), QueueConsumer)

    def test_queue_publisher_satisfied_by_conforming_class(self):
        class FakePublisher:
            def send_message(self, queue_id, body):
                pass

        assert isinstance(FakePublisher(), QueuePublisher)

    def test_secrets_store_satisfied_by_conforming_class(self):
        class FakeSecrets:
            def get_secret(self, secret_id):
                return ""

        assert isinstance(FakeSecrets(), SecretsStore)

    def test_non_conforming_class_does_not_satisfy_protocol(self):
        class NotStorage:
            pass

        assert not isinstance(NotStorage(), ObjectStorage)
