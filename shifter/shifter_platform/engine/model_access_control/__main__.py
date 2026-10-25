"""Start the dedicated TLS listener after normal Engine secret hydration."""

import os
import re
from collections.abc import Mapping
from uuid import UUID

from shared.model_access.diagnostics import isolate_transport_diagnostics


def _identity_configuration() -> tuple[str, str, str, str, str, str]:
    """Reject incomplete or overlapping workload identities before serving."""
    provider = os.environ.get("MODEL_CONTROL_PROVIDER", "gcp")
    audience = os.environ["MODEL_CONTROL_AUDIENCE"]
    broker = os.environ["MODEL_CONTROL_BROKER_SUBJECT"]
    provisioner = os.environ["MODEL_CONTROL_PROVISIONER_SUBJECT"]
    if not broker or not provisioner or broker == provisioner or provider not in {"aws", "gcp"}:
        raise RuntimeError("model control requires distinct workload identities")
    broker_id = os.environ.get("MODEL_CONTROL_BROKER_SUBJECT_ID", "")
    provisioner_id = os.environ.get("MODEL_CONTROL_PROVISIONER_SUBJECT_ID", "")
    if provider == "gcp" and (
        not re.fullmatch(r"\d{10,32}", broker_id, flags=re.ASCII)
        or not re.fullmatch(r"\d{10,32}", provisioner_id, flags=re.ASCII)
        or broker_id == provisioner_id
    ):
        raise RuntimeError("model control requires distinct immutable workload subjects")
    return provider, audience, broker, provisioner, broker_id, provisioner_id


def main() -> None:
    """Keep rejected configuration and credential diagnostics off stderr."""
    isolate_transport_diagnostics()
    try:
        _main()
    except Exception:
        raise SystemExit("model control configuration is invalid") from None


def _main() -> None:
    """Fail closed on missing catalog or workload-identity configuration."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()
    import requests
    import uvicorn
    from django.conf import settings
    from django.db import connection
    from google.auth.transport import Response
    from google.auth.transport.requests import Request

    from engine.model_access_control.server import ControlApplication
    from shared.model_access import ContractError
    from shared.model_access.control_identity import verify_aws_control_assertion, verify_google_control_assertion
    from shared.model_access.http import MAX_HEADER_BYTES
    from shared.model_access.network import private_listener_address

    if not settings.MODEL_ACCESS_ENABLED or settings.MODEL_ACCESS_CATALOG is None:
        raise RuntimeError("model control requires enabled model access")
    provider, audience, broker, provisioner, broker_id, provisioner_id = _identity_configuration()
    session = requests.Session()
    session.trust_env = False
    google_request = Request(session=session)

    def bounded_google_request(
        url: str,
        method: str = "GET",
        body: bytes | None = None,
        headers: Mapping[str, str] | None = None,
        **kwargs: object,
    ) -> Response:
        """Limit certificate retrieval during workload verification to two seconds."""
        kwargs["timeout"] = 2
        return google_request(url, method=method, body=body, headers=headers, **kwargs)

    def verify(assertion: str, *, operation_id: UUID | None) -> None:
        """Verify a distinct broker or operation-bound provisioner identity."""
        expected = provisioner if operation_id else broker
        bound_audience = f"{audience}:enroll:{operation_id}" if operation_id else audience
        if provider == "gcp":
            verify_google_control_assertion(
                assertion,
                audience=bound_audience,
                expected_subject=expected,
                expected_subject_id=provisioner_id if operation_id else broker_id,
                request=bounded_google_request,
            )
        else:
            verify_aws_control_assertion(
                assertion,
                audience=bound_audience,
                expected_role=expected,
                region=os.environ["MODEL_CONTROL_REGION"],
                session=session,
            )

    def ready() -> bool:
        """Admit readiness only while the Engine database responds."""
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                return cursor.fetchone() == (1,)
        except Exception:
            return False

    try:
        uvicorn.run(
            ControlApplication(verify_identity=verify, ready=ready),
            # Bind the private pod interface; TLS and NetworkPolicy remain mandatory.
            host=private_listener_address(os.environ["MODEL_CONTROL_BIND_ADDRESS"]),
            port=8444,
            ssl_certfile=os.environ["MODEL_CONTROL_TLS_CERT"],
            ssl_keyfile=os.environ["MODEL_CONTROL_TLS_KEY"],
            proxy_headers=False,
            access_log=False,
            server_header=False,
            lifespan="off",
            limit_concurrency=128,
            backlog=128,
            timeout_keep_alive=5,
            timeout_graceful_shutdown=130,
            http="h11",
            ws="none",
            h11_max_incomplete_event_size=MAX_HEADER_BYTES,
        )
    except ContractError:
        raise RuntimeError("model control configuration is invalid") from None
    finally:
        session.close()


if __name__ == "__main__":
    main()
