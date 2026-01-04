"""Pytest fixtures for WebSocket consumer tests.

These fixtures provide mocked dependencies for testing SSHConsumer
and RangeStatusConsumer without requiring real WebSocket connections,
database queries, or SSH sessions.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser

from shared.enums import RangeStatus
from shared.schemas import InstanceContext, RangeContext

User = get_user_model()


# =============================================================================
# User Fixtures
# =============================================================================


@pytest.fixture
def mock_user():
    """Create a mock authenticated user."""
    user = MagicMock(spec=User)
    user.id = 1
    user.username = "testuser"
    user.email = "test@example.com"
    user.is_authenticated = True
    return user


@pytest.fixture
def anonymous_user():
    """Return an AnonymousUser instance."""
    return AnonymousUser()


# =============================================================================
# Range and Instance Fixtures
# =============================================================================


@pytest.fixture
def mock_instance():
    """Create a mock InstanceContext."""
    return InstanceContext(
        uuid="test-instance-uuid-1234",
        role="attacker",
        os_type="kali",
        join_domain=False,
    )


@pytest.fixture
def mock_range_context(mock_instance):
    """Create a mock RangeContext with READY status."""
    return RangeContext(
        range_id=42,
        scenario_id="test-scenario",
        user_id=1,
        status=RangeStatus.READY,
        instances=[mock_instance],
        agent_name="test-agent",
    )


@pytest.fixture
def mock_range_context_not_ready(mock_instance):
    """Create a mock RangeContext with PROVISIONING status."""
    return RangeContext(
        range_id=42,
        scenario_id="test-scenario",
        user_id=1,
        status=RangeStatus.PROVISIONING,
        instances=[mock_instance],
        agent_name="test-agent",
    )


@pytest.fixture
def mock_range_instance():
    """Create a mock range instance object (for RangeStatusConsumer)."""
    range_instance = MagicMock()
    range_instance.status = RangeStatus.READY.value
    return range_instance


# =============================================================================
# SSH Connection Fixtures
# =============================================================================


@pytest.fixture
def mock_ssh_connection():
    """Create a mock SSH connection object."""
    ssh_conn = AsyncMock()
    ssh_conn.connect = AsyncMock()
    ssh_conn.disconnect = AsyncMock()
    ssh_conn.send = AsyncMock()
    ssh_conn.receive = AsyncMock(return_value=b"output data")
    ssh_conn.resize = AsyncMock()
    return ssh_conn


# =============================================================================
# Channel Layer Fixtures
# =============================================================================


@pytest.fixture
def mock_channel_layer():
    """Create a mock channel layer for group operations."""
    channel_layer = AsyncMock()
    channel_layer.group_add = AsyncMock()
    channel_layer.group_discard = AsyncMock()
    channel_layer.send = AsyncMock()
    return channel_layer


# =============================================================================
# WebSocket Scope Fixtures
# =============================================================================


@pytest.fixture
def websocket_scope_authenticated(mock_user):
    """Create an authenticated WebSocket scope."""
    return {
        "type": "websocket",
        "user": mock_user,
        "url_route": {
            "kwargs": {
                "instance_uuid": "test-instance-uuid-1234",
            }
        },
    }


@pytest.fixture
def websocket_scope_unauthenticated(anonymous_user):
    """Create an unauthenticated WebSocket scope."""
    return {
        "type": "websocket",
        "user": anonymous_user,
        "url_route": {
            "kwargs": {
                "instance_uuid": "test-instance-uuid-1234",
            }
        },
    }


@pytest.fixture
def websocket_scope_no_user():
    """Create a WebSocket scope with no user."""
    return {
        "type": "websocket",
        "user": None,
        "url_route": {
            "kwargs": {
                "instance_uuid": "test-instance-uuid-1234",
            }
        },
    }


@pytest.fixture
def websocket_scope_no_instance_uuid(mock_user):
    """Create a WebSocket scope without instance_uuid."""
    return {
        "type": "websocket",
        "user": mock_user,
        "url_route": {
            "kwargs": {},
        },
    }


@pytest.fixture
def websocket_scope_range_status(mock_user):
    """Create an authenticated WebSocket scope for range status."""
    return {
        "type": "websocket",
        "user": mock_user,
        "url_route": {
            "kwargs": {
                "range_id": "42",
            }
        },
    }


@pytest.fixture
def websocket_scope_range_status_unauthenticated(anonymous_user):
    """Create an unauthenticated WebSocket scope for range status."""
    return {
        "type": "websocket",
        "user": anonymous_user,
        "url_route": {
            "kwargs": {
                "range_id": "42",
            }
        },
    }


# =============================================================================
# Consumer Factory Fixtures
# =============================================================================


@pytest.fixture
def ssh_consumer_factory():
    """Factory to create SSHConsumer instances with custom scope."""
    from mission_control.consumers import SSHConsumer

    def _create(scope):
        consumer = SSHConsumer()
        consumer.scope = scope
        consumer.channel_name = "test-channel"
        consumer.close = AsyncMock()
        consumer.accept = AsyncMock()
        consumer.send = AsyncMock()
        return consumer

    return _create


@pytest.fixture
def range_status_consumer_factory(mock_channel_layer):
    """Factory to create RangeStatusConsumer instances with custom scope."""
    from mission_control.consumers import RangeStatusConsumer

    def _create(scope):
        consumer = RangeStatusConsumer()
        consumer.scope = scope
        consumer.channel_name = "test-channel"
        consumer.channel_layer = mock_channel_layer
        consumer.close = AsyncMock()
        consumer.accept = AsyncMock()
        consumer.send = AsyncMock()
        return consumer

    return _create
