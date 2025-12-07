from unittest.mock import patch

from django.test import Client


def test_health_returns_200_when_db_healthy():
    """Health endpoint returns 200 when all checks pass."""
    with patch("health_check.db.backends.DatabaseBackend.check_status"):
        client = Client()
        response = client.get("/health/")
        assert response.status_code == 200
