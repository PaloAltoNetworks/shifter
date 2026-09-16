"""Worker HTTP transport cannot leak its bearer token through redirects or URLs."""

from uuid import uuid4

import pytest

from preparation.worker_client import WorkerClient


class Response:
    def __init__(self, status, body):
        self.status_code, self.body = status, body

    def iter_content(self, chunk_size):
        yield self.body

    def close(self):
        pass


class Session:
    def __init__(self, response):
        self.response, self.calls = response, []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.response


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://tenant.example/",
        "https://user:pass@tenant.example/",
        "https://tenant.example/?token=bad",
        "https://tenant.example:8443/api/v1/cms/artifact-preparation/workers/",
        "https://tenant.example:bad/api/v1/cms/artifact-preparation/workers/",
    ],
)
def test_noncanonical_endpoint_is_rejected_before_sending_a_credential(endpoint):
    with pytest.raises(ValueError):
        WorkerClient(endpoint, uuid4(), "opaque", Session(Response(200, b"{}")))


@pytest.mark.parametrize("status,body", [(302, b"{}"), (200, b"x" * 262145), (200, b'{"id":1,"id":2}')])
def test_redirect_oversize_and_ambiguous_json_are_not_worker_input(status, body):
    session = Session(Response(status, body))
    client = WorkerClient("https://tenant.example/api/v1/cms/artifact-preparation/workers/", uuid4(), "opaque", session)
    with pytest.raises(ValueError):
        client.read()
    assert len(session.calls) == 1
    assert session.calls[0][2]["allow_redirects"] is False
    assert "opaque" not in session.calls[0][1]


def test_result_receipt_is_distinct_from_successful_artifact_admission():
    session = Session(Response(202, b'{"status":"received"}'))
    client = WorkerClient("https://tenant.example/api/v1/cms/artifact-preparation/workers/", uuid4(), "opaque", session)
    client.submit({"status": "failed"})
    assert session.calls[0][0] == "POST"


@pytest.mark.parametrize("body", [b'{"status":"other"}', b"{}"])
def test_result_submission_requires_the_exact_durable_receipt(body):
    session = Session(Response(202, body))
    client = WorkerClient("https://tenant.example/api/v1/cms/artifact-preparation/workers/", uuid4(), "opaque", session)

    with pytest.raises(ValueError, match="was not acknowledged"):
        client.submit({"status": "failed"})
