"""Start the broker without importing Django or application secret hydration."""

import base64
import os
from pathlib import Path

from model_broker.control import ControlClient
from model_broker.identity import WorkloadIdentity
from model_broker.provider_credentials import ProviderCredentials
from model_broker.providers import ProviderRegistry
from model_broker.server import BrokerApplication
from shared.model_access.diagnostics import isolate_transport_diagnostics
from shared.model_access.messages import strict_json
from shared.model_access.network import private_listener_address
from shared.model_access.provider_runtime import ProviderInventory
from shared.model_access.runtime import load_mounted_catalog


def application_from_environment() -> BrokerApplication:
    """Validate every mounted configuration binding before opening a listener."""
    catalog = load_mounted_catalog(
        enabled=True,
        path=os.environ["MODEL_BROKER_CATALOG_PATH"],
        expected_digest=os.environ["MODEL_BROKER_CATALOG_DIGEST"],
    )
    if catalog is None:
        raise ValueError("model broker requires an enabled mounted catalog")
    with Path(os.environ["MODEL_BROKER_PROVIDERS_PATH"]).open("rb") as stream:
        inventory = ProviderInventory.model_validate(strict_json(stream.read(98_305), limit=98_304))
    targets = {target.shard_id: target for target in inventory.targets}
    for shard in catalog.shards:
        if shard.enabled:
            if shard.shard_id not in targets:
                raise ValueError("enabled model shard is absent from provider inventory")
            targets[shard.shard_id].bind(shard)
    with Path(os.environ["MODEL_BROKER_FINGERPRINT_KEY_PATH"]).open("rb") as stream:
        fingerprint_key = stream.read(65)
    if not 32 <= len(fingerprint_key) <= 64:
        raise ValueError("invalid broker fingerprint key length")
    previous_keys = {}
    previous_path = os.environ.get("MODEL_BROKER_FINGERPRINT_PREVIOUS_KEYS_PATH")
    if previous_path:
        with Path(previous_path).open("rb") as stream:
            previous = strict_json(stream.read(4097), limit=4096)
        previous_keys = {version: base64.b64decode(value, validate=True) for version, value in previous.items()}
    control = ControlClient(
        url=os.environ["MODEL_BROKER_CONTROL_URL"],
        ca_file=os.environ["MODEL_BROKER_CA_FILE"],
        identity=WorkloadIdentity(
            provider=os.environ["MODEL_BROKER_PROVIDER"],
            region=os.environ["MODEL_BROKER_REGION"],
            audience=os.environ["MODEL_BROKER_CONTROL_AUDIENCE"],
        ),
    )
    return BrokerApplication(
        control=control,
        providers=ProviderRegistry(inventory=inventory, credentials=ProviderCredentials()),
        fingerprint_key=fingerprint_key,
        key_version=os.environ["MODEL_BROKER_FINGERPRINT_KEY_VERSION"],
        previous_keys=previous_keys,
    )


def main() -> None:
    """Emit only a fixed startup failure; validation inputs may contain secrets."""
    isolate_transport_diagnostics()
    try:
        _main()
    except Exception:
        raise SystemExit("model broker configuration is invalid") from None


def _main() -> None:
    """TLS and real socket peers are mandatory; forwarded identity is disabled."""
    import uvicorn

    from model_broker.runtime_server import DrainingServer
    from shared.model_access.http import MAX_HEADER_BYTES

    app = application_from_environment()
    DrainingServer(
        uvicorn.Config(
            app,
            # Bind the private pod interface; TLS and NetworkPolicy remain mandatory.
            host=private_listener_address(os.environ["MODEL_BROKER_BIND_ADDRESS"]),
            port=8443,
            ssl_certfile=os.environ["MODEL_BROKER_TLS_CERT"],
            ssl_keyfile=os.environ["MODEL_BROKER_TLS_KEY"],
            proxy_headers=False,
            access_log=False,
            server_header=False,
            limit_concurrency=128,
            backlog=128,
            timeout_keep_alive=5,
            timeout_graceful_shutdown=130,
            http="h11",
            ws="none",
            h11_max_incomplete_event_size=MAX_HEADER_BYTES,
        )
    ).run()


if __name__ == "__main__":
    main()
