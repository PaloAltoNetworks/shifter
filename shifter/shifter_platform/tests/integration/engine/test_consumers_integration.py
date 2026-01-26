"""Integration tests for WebSocket consumers.

Tests consumer connection and hydration with real database objects.
Channel layer operations use mocks since they require Redis.
"""

import json
import uuid
from unittest.mock import AsyncMock

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser

from cms.models import RangeInstance
from cms.models import Request as CMSRequest
from engine.models import Range, Request
from mission_control.consumers import RangeStatusConsumer
from shared.enums import RequestType, WebSocketCloseCode

User = get_user_model()


@pytest.fixture
def user(db):
    """Create a test user."""
    return User.objects.create_user(
        username="testuser@example.com",
        email="testuser@example.com",
        password="testpass123",
    )


@pytest.fixture
def other_user(db):
    """Create another test user for ownership tests."""
    return User.objects.create_user(
        username="otheruser@example.com",
        email="otheruser@example.com",
        password="otherpass123",
    )


@pytest.fixture
def engine_request(db, user):
    """Create an Engine Request."""
    return Request.objects.create(
        request_id=uuid.uuid4(),
        request_type=RequestType.RANGE.value,
        user=user,
    )


@pytest.fixture
def cms_request(db, user, engine_request):
    """Create a CMS Request linked to Engine Request."""
    return CMSRequest.objects.create(
        request_id=engine_request.request_id,
        request_type=RequestType.RANGE.value,
        user=user,
    )


@pytest.fixture
def range_ready_with_cms(db, user, engine_request, cms_request):
    """Create Engine Range with corresponding CMS RangeInstance."""
    # Create Engine Range
    engine_range = Range.objects.create(
        uuid=uuid.uuid4(),
        user=user,
        request=engine_request,
        status=Range.Status.READY,
        subnet_index=1,
        provisioned_instances=[
            {
                "uuid": "attacker-uuid-123",
                "role": "attacker",
                "os_type": "kali",
                "private_ip": "10.1.1.10",
            },
        ],
    )

    # Create CMS RangeInstance (linked via request_id)
    cms_range = RangeInstance.objects.create(
        request=cms_request,
        scenario_id="test_scenario",
        user_id=user.id,
        status="ready",
    )

    return engine_range, cms_range


@pytest.fixture
def consumer_with_mocked_channel():
    """Create a RangeStatusConsumer with mocked channel layer."""
    c = RangeStatusConsumer()
    c.channel_name = "test-channel"
    c.channel_layer = AsyncMock()
    c.close = AsyncMock()
    c.accept = AsyncMock()
    c.send = AsyncMock()
    return c


# =============================================================================
# RangeStatusConsumer integration tests with real DB
# =============================================================================


@pytest.mark.django_db(transaction=True)
class TestRangeStatusConsumerIntegration:
    """Integration tests for RangeStatusConsumer with real DB objects."""

    @pytest.mark.asyncio
    async def test_connect_with_real_range_hydrates_status(
        self, consumer_with_mocked_channel, user, range_ready_with_cms
    ):
        """Consumer hydrates status from real database range."""
        engine_range, _cms_range = range_ready_with_cms
        consumer = consumer_with_mocked_channel
        request_id = str(engine_range.request.request_id)

        consumer.scope = {
            "type": "websocket",
            "user": user,
            "url_route": {"kwargs": {"request_id": request_id}},
        }

        await consumer.connect()

        # Should accept connection
        consumer.accept.assert_awaited_once()

        # Should send hydrated status from real DB
        consumer.send.assert_awaited_once()
        message = json.loads(consumer.send.call_args[1]["text_data"])
        assert message["type"] == "status"
        assert message["request_id"] == request_id
        assert message["status"] == "ready"

    @pytest.mark.asyncio
    async def test_connect_rejects_other_users_range(
        self, consumer_with_mocked_channel, other_user, range_ready_with_cms
    ):
        """Consumer rejects connection for range owned by another user."""
        engine_range, _cms_range = range_ready_with_cms
        consumer = consumer_with_mocked_channel
        request_id = str(engine_range.request.request_id)

        # Use other_user who doesn't own the range
        consumer.scope = {
            "type": "websocket",
            "user": other_user,
            "url_route": {"kwargs": {"request_id": request_id}},
        }

        await consumer.connect()

        # Should reject with NOT_FOUND (CMS ownership check fails)
        consumer.close.assert_awaited_once_with(code=WebSocketCloseCode.NOT_FOUND)
        consumer.accept.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_connect_rejects_nonexistent_range(self, consumer_with_mocked_channel, user):
        """Consumer rejects connection for non-existent range."""
        consumer = consumer_with_mocked_channel
        fake_request_id = str(uuid.uuid4())

        consumer.scope = {
            "type": "websocket",
            "user": user,
            "url_route": {"kwargs": {"request_id": fake_request_id}},
        }

        await consumer.connect()

        consumer.close.assert_awaited_once_with(code=WebSocketCloseCode.NOT_FOUND)
        consumer.accept.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_connect_rejects_unauthenticated(self, consumer_with_mocked_channel):
        """Consumer rejects unauthenticated connections."""
        consumer = consumer_with_mocked_channel

        consumer.scope = {
            "type": "websocket",
            "user": AnonymousUser(),
            "url_route": {"kwargs": {"request_id": str(uuid.uuid4())}},
        }

        await consumer.connect()

        consumer.close.assert_awaited_once_with(code=WebSocketCloseCode.NOT_AUTHENTICATED)
        consumer.accept.assert_not_awaited()


# =============================================================================
# Range model lookup integration tests
# =============================================================================


@pytest.mark.django_db
class TestRangeModelLookupIntegration:
    """Integration tests for Range model queries used by consumers."""

    def test_range_found_by_request_id(self, user, engine_request):
        """Range can be found via request_id relationship."""
        range_obj = Range.objects.create(
            uuid=uuid.uuid4(),
            user=user,
            request=engine_request,
            status=Range.Status.PROVISIONING,
            subnet_index=5,
        )

        found = Range.objects.filter(request__request_id=engine_request.request_id).first()

        assert found is not None
        assert found.id == range_obj.id
        assert found.status == Range.Status.PROVISIONING

    def test_range_not_found_for_unknown_request_id(self):
        """Range query returns None for unknown request_id."""
        found = Range.objects.filter(request__request_id=uuid.uuid4()).first()

        assert found is None

    def test_range_status_reflects_database_updates(self, user, engine_request):
        """Range status changes are visible in subsequent queries."""
        range_obj = Range.objects.create(
            uuid=uuid.uuid4(),
            user=user,
            request=engine_request,
            status=Range.Status.PROVISIONING,
            subnet_index=6,
        )

        # Update status
        range_obj.status = Range.Status.READY
        range_obj.save(update_fields=["status"])

        # Fresh query should see new status
        found = Range.objects.get(id=range_obj.id)
        assert found.status == Range.Status.READY


# =============================================================================
# CMS Range lookup integration tests (for consumer hydration)
# =============================================================================


@pytest.mark.django_db
class TestRangeInstanceLookupIntegration:
    """Integration tests for CMS Range queries used by RangeStatusConsumer."""

    def test_range_instance_found_via_request_id(self, user, cms_request):
        """RangeInstance can be found via request_id."""
        RangeInstance.objects.create(
            request=cms_request,
            scenario_id="test_scenario",
            user_id=user.id,
            status="provisioning",
        )

        found = RangeInstance.objects.filter(
            request__request_id=cms_request.request_id,
            user_id=user.id,
        ).first()

        assert found is not None
        assert found.status == "provisioning"

    def test_range_instance_not_found_for_other_user(self, user, other_user, cms_request):
        """RangeInstance not found when queried by non-owner."""
        RangeInstance.objects.create(
            request=cms_request,
            scenario_id="test_scenario",
            user_id=user.id,
            status="ready",
        )

        found = RangeInstance.objects.filter(
            request__request_id=cms_request.request_id,
            user_id=other_user.id,  # Not the owner
        ).first()

        assert found is None


# =============================================================================
# Status synchronization integration tests
# =============================================================================


@pytest.mark.django_db
class TestStatusSynchronizationIntegration:
    """Integration tests for status consistency between Engine and CMS."""

    def test_engine_and_cms_ranges_can_have_same_request_id(self, user, engine_request, cms_request):
        """Engine and CMS ranges can be correlated via shared request_id."""
        # Create Engine Range
        engine_range = Range.objects.create(
            uuid=uuid.uuid4(),
            user=user,
            request=engine_request,
            status=Range.Status.READY,
            subnet_index=10,
        )

        # Create CMS RangeInstance
        RangeInstance.objects.create(
            request=cms_request,
            scenario_id="test_scenario",
            user_id=user.id,
            status="ready",
        )

        # Both should be findable via the same request_id
        assert engine_range.request.request_id == cms_request.request_id

        engine_found = Range.objects.filter(request__request_id=cms_request.request_id).first()
        cms_found = RangeInstance.objects.filter(request__request_id=engine_request.request_id).first()

        assert engine_found is not None
        assert cms_found is not None
