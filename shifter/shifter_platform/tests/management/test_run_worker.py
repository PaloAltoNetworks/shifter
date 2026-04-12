"""Tests for generic queue identifier handling in run_worker."""

from shared.management.commands.run_worker import _get_queue_consumer_id


class TestGetQueueConsumerId:
    """Workers prefer consumer_id but retain the legacy url alias."""

    def test_prefers_consumer_id(self) -> None:
        config = {
            "consumer_id": "projects/test/subscriptions/shifter-gcp-dev-cms",
            "url": "legacy-url",
        }

        assert _get_queue_consumer_id(config) == "projects/test/subscriptions/shifter-gcp-dev-cms"

    def test_falls_back_to_url(self) -> None:
        config = {"url": "https://sqs.us-east-2.amazonaws.com/123/cms-tasks"}

        assert _get_queue_consumer_id(config) == "https://sqs.us-east-2.amazonaws.com/123/cms-tasks"
