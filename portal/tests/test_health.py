from django.test import Client


def test_health_returns_200():
    """Health endpoint returns 200 OK."""
    client = Client()
    response = client.get("/health/")
    assert response.status_code == 200
    assert response.content == b"OK"


def test_health_without_trailing_slash():
    """Health endpoint works without trailing slash (ALB sends /health)."""
    client = Client()
    response = client.get("/health")
    assert response.status_code == 200
    assert response.content == b"OK"
